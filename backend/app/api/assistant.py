from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.assistant.blocklist import contains_blocked_command
from app.assistant.service import AssistantChatService, AssistantEvent
from app.assistant.tools import ToolDispatcher
from app.container import ApplicationContainer
from app.core.errors import (
    AIGatewayDisabledError,
    AutoModeRequiresAcknowledgmentError,
    BlockedCommandError,
)
from app.models import AssistantSession, AssistantSessionMode
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.events import EventRepository
from app.repositories.provider_profiles import ProviderProfileRepository
from app.schemas.assistant import AssistantSessionCreate, AssistantSessionView
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
        mode=chat_session.mode,
        auto_apply_count=chat_session.auto_apply_count,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


@sessions_router.get("", response_model=list[AssistantSessionView])
def list_sessions(_auth: Authenticated, session: SessionDependency, container: ContainerDependency):
    return [_session_view(s) for s in AssistantSessionRepository(session).list()]


@sessions_router.post("", response_model=AssistantSessionView, status_code=status.HTTP_201_CREATED)
def create_session(
    request: AssistantSessionCreate,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    chat_session = AssistantSessionRepository(session).add(
        provider_profile_id=request.provider_profile_id
    )
    session.commit()
    return _session_view(chat_session)


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


def _build_tool_dispatcher(db_session: Session, container: ApplicationContainer) -> ToolDispatcher:
    devices = DeviceService(
        db_session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
        connection_gate=container.connection_gate,
    )
    snapshots = SnapshotService(
        db_session, store=container.snapshot_store, devices=devices, drivers=container.drivers
    )
    return ToolDispatcher(devices=devices, snapshots=snapshots, events=EventRepository(db_session))


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
        service = AssistantChatService(
            db_session,
            provider_client=container.ai_provider_client,
            sessions=AssistantSessionRepository(db_session),
            messages=AssistantMessageRepository(db_session),
            profiles=ProviderProfileRepository(db_session),
            vault=container.provider_key_vault,
            tools=_build_tool_dispatcher(db_session, container),
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
                    async for event in service.handle_user_message(session_uuid, content):
                        await websocket.send_json(_event_to_frame(event))
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
