from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.assistant.blocklist import contains_blocked_command
from app.assistant.client import AIProviderConnectionError
from app.assistant.sanitize import scrub_secret_text
from app.assistant.service import AssistantChatService, AssistantEvent
from app.assistant.tools import ToolDispatcher
from app.changes.service import ChangeService
from app.container import ApplicationContainer
from app.core.errors import (
    AIGatewayDisabledError,
    AppError,
    AutoModeRequiresAcknowledgmentError,
    BlockedCommandError,
)
from app.models import AssistantSession, AssistantSessionMode
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.events import EventRepository
from app.repositories.provider_profiles import ProviderProfileRepository
from app.schemas.assistant import (
    AssistantMessageView,
    AssistantSessionCreate,
    AssistantSessionUpdate,
    AssistantSessionView,
)
from app.schemas.common import APIModel
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService


def _require_enabled(container: ContainerDependency) -> None:
    if not container.settings.ai_gateway_enabled:
        raise AIGatewayDisabledError()


sessions_router = APIRouter(
    prefix="/assistant-sessions",
    tags=["assistant"],
    dependencies=[Depends(_require_enabled)],
)


def _session_view(chat_session: AssistantSession) -> AssistantSessionView:
    return AssistantSessionView(
        id=chat_session.id,
        provider_profile_id=chat_session.provider_profile_id,
        model_id=chat_session.model_id,
        device_id=chat_session.device_id,
        scope_device_ids=[UUID(value) for value in chat_session.scope_device_ids],
        mode=chat_session.mode,
        supports_streaming=chat_session.supports_streaming,
        supports_tool_calling=chat_session.supports_tool_calling,
        auto_apply_count=chat_session.auto_apply_count,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


@sessions_router.get("", response_model=list[AssistantSessionView])
def list_sessions(
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
    device_id: UUID | None = None,
    scope: Literal["all", "device", "workspace"] = "all",
):
    # A device's inspector must not see another device's conversations, and
    # the workspace view must not be cluttered by every device chat -- so the
    # caller says which slice it wants instead of filtering client-side.
    repository = AssistantSessionRepository(session)
    if scope == "device":
        sessions = repository.list(device_id=device_id, device_scoped=True)
    elif scope == "workspace":
        sessions = repository.list(device_id=None, device_scoped=True)
    else:
        sessions = repository.list()
    return [_session_view(s) for s in sessions]


@sessions_router.post("", response_model=AssistantSessionView, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: AssistantSessionCreate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    # One provider profile is just a connection (base_url + key) that can
    # legitimately serve many models, so capability support is probed here,
    # against the specific model this session picked -- not cached on the
    # profile, where it could only ever be right for one model at a time.
    profile = ProviderProfileRepository(session).get(request.provider_profile_id)
    material = container.provider_key_vault.decrypt(profile)
    try:
        capabilities = await container.ai_client_for(profile.provider_type).probe_capabilities(
            base_url=profile.base_url, api_key=material.api_key, model_id=request.model_id
        )
    except AIProviderConnectionError as exc:
        raise HTTPException(
            status_code=502, detail="Could not reach the configured endpoint"
        ) from exc
    chat_session = AssistantSessionRepository(session).add(
        provider_profile_id=request.provider_profile_id,
        model_id=request.model_id,
        device_id=request.device_id,
        scope_device_ids=[str(value) for value in request.scope_device_ids],
        supports_streaming=capabilities.supports_streaming,
        supports_tool_calling=capabilities.supports_tool_calling,
    )
    session.commit()
    return _session_view(chat_session)


@sessions_router.patch("/{session_id}", response_model=AssistantSessionView)
async def update_session_model(
    session_id: UUID,
    request: AssistantSessionUpdate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    """Repoint a live conversation, keeping its history.

    Covers two independent edits the sidebar makes without leaving the thread:
    the model it runs on, and which devices it is about. Each field is
    optional so one picker cannot clobber the other's value.

    Switching model re-probes capabilities for the same reason
    `create_session` probes them: they belong to the model, not the profile,
    so carrying the previous model's flags forward could advertise tool
    calling a model does not have.
    """
    repository = AssistantSessionRepository(session)
    chat_session = repository.get(session_id)

    if request.scope_device_ids is not None:
        repository.set_scope(chat_session, [str(value) for value in request.scope_device_ids])

    if request.provider_profile_id is not None and request.model_id is not None:
        profile = ProviderProfileRepository(session).get(request.provider_profile_id)
        material = container.provider_key_vault.decrypt(profile)
        try:
            capabilities = await container.ai_client_for(profile.provider_type).probe_capabilities(
                base_url=profile.base_url, api_key=material.api_key, model_id=request.model_id
            )
        except AIProviderConnectionError as exc:
            # Nothing is committed on this path, so the session keeps the
            # model that still works rather than being left pointing at one
            # that could not be reached.
            session.rollback()
            raise HTTPException(
                status_code=502, detail="Could not reach the configured endpoint"
            ) from exc
        repository.set_model(
            chat_session,
            provider_profile_id=request.provider_profile_id,
            model_id=request.model_id,
            supports_streaming=capabilities.supports_streaming,
            supports_tool_calling=capabilities.supports_tool_calling,
        )

    session.commit()
    return _session_view(chat_session)


@sessions_router.get("/{session_id}/messages", response_model=list[AssistantMessageView])
def list_session_messages(
    session_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    # 404s for an unknown session rather than returning an empty list, so a
    # stale session id in the UI is distinguishable from a genuinely empty
    # conversation.
    AssistantSessionRepository(session).get(session_id)
    return AssistantMessageRepository(session).list_for_session(session_id)


class StageCommandRequest(APIModel):
    command: str


@sessions_router.post("/{session_id}/stage-command")
def stage_command(
    session_id: UUID,
    request: StageCommandRequest,
    _auth: Authenticated,
):
    if contains_blocked_command(request.command):
        raise BlockedCommandError()
    return {"allowed": True}


router = APIRouter()


def _event_to_frame(event: AssistantEvent) -> dict[str, object]:
    frame: dict[str, object] = {"type": event.type}
    if event.content is not None:
        frame["content"] = event.content
    if event.tool_name is not None:
        frame["tool"] = event.tool_name
    if event.tool_payload is not None:
        frame["payload"] = event.tool_payload
    if event.error_code is not None:
        frame["code"] = event.error_code
    return frame


def _build_device_service(db_session: Session, container: ApplicationContainer) -> DeviceService:
    return DeviceService(
        db_session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
        connection_gate=container.connection_gate,
    )


def _build_tool_dispatcher(
    db_session: Session, container: ApplicationContainer, devices: DeviceService
) -> ToolDispatcher:
    snapshots = SnapshotService(
        db_session, store=container.snapshot_store, devices=devices, drivers=container.drivers
    )
    return ToolDispatcher(devices=devices, snapshots=snapshots, events=EventRepository(db_session))


def _build_change_service(
    db_session: Session, container: ApplicationContainer, devices: DeviceService
) -> ChangeService:
    snapshots = SnapshotService(
        db_session, store=container.snapshot_store, devices=devices, drivers=container.drivers
    )
    return ChangeService(
        db_session,
        settings=container.settings,
        drivers=container.drivers,
        devices=devices,
        snapshots=snapshots,
    )


@router.websocket("/ws/assistant/{session_id}")
async def assistant_chat(websocket: WebSocket, session_id: str) -> None:
    container: ApplicationContainer = websocket.app.state.container
    if not container.settings.ai_gateway_enabled:
        await websocket.close(code=4403, reason="AI gateway disabled by policy")
        return
    token = websocket.cookies.get(container.settings.session_cookie_name)
    if token is None or container.session_tokens.verify(token) is None:
        await websocket.close(code=4401, reason="Authentication required")
        return
    origin = websocket.headers.get("origin")
    if origin is None or origin.rstrip("/") not in container.settings.trusted_origins():
        await websocket.close(code=4403, reason="Origin rejected")
        return

    await websocket.accept()
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        await websocket.close(code=4400, reason="Invalid session id")
        return

    with container.session_factory() as db_session:
        devices = _build_device_service(db_session, container)
        changes = (
            _build_change_service(db_session, container, devices)
            if container.settings.structured_writes_enabled
            else None
        )
        service = AssistantChatService(
            db_session,
            provider_client_for=container.ai_client_for,
            sessions=AssistantSessionRepository(db_session),
            messages=AssistantMessageRepository(db_session),
            profiles=ProviderProfileRepository(db_session),
            vault=container.provider_key_vault,
            tools=_build_tool_dispatcher(db_session, container, devices),
            changes=changes,
            devices=devices,
        )
        try:
            while True:
                message = await websocket.receive_json()
                message_type = message.get("type")
                if message_type == "user_message":
                    content = message.get("content")
                    if not isinstance(content, str) or not content.strip():
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "invalid_message",
                                "message": "content is required",
                            }
                        )
                        continue
                    # A provider failure is the most likely thing to go wrong
                    # here -- a mistyped key, an expired one, no credit, a
                    # rate limit, a model name the provider does not have.
                    # Letting it propagate tore down the socket, so the chat
                    # went silent with nothing but "Disconnected" to explain
                    # it. Report it and keep the conversation open instead.
                    try:
                        async for event in service.handle_user_message(session_uuid, content):
                            await websocket.send_json(_event_to_frame(event))
                    except AIProviderConnectionError as exc:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "provider_unreachable",
                                "message": (
                                    "Could not reach the AI provider. Check the profile's API "
                                    "key, model name and endpoint. "
                                    f"({scrub_secret_text(str(exc))[:400]})"
                                ),
                            }
                        )
                    except AppError as exc:
                        await websocket.send_json(
                            {"type": "error", "code": exc.code, "message": str(exc)}
                        )
                elif message_type == "set_mode":
                    mode_value = message.get("mode")
                    risk_acknowledged = bool(message.get("risk_acknowledged", False))
                    try:
                        service.set_mode(
                            session_uuid,
                            AssistantSessionMode(mode_value),
                            risk_acknowledged=risk_acknowledged,
                        )
                        await websocket.send_json({"type": "mode_changed", "mode": mode_value})
                    except AutoModeRequiresAcknowledgmentError:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "code": "auto_mode_requires_acknowledgment",
                                "message": "Confirm the risk before enabling Auto mode",
                            }
                        )
                    except ValueError:
                        await websocket.send_json(
                            {"type": "error", "code": "invalid_message", "message": "unknown mode"}
                        )
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_message",
                            "message": "unknown message type",
                        }
                    )
        except WebSocketDisconnect:
            return
