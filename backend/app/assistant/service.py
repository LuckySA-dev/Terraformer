from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.assistant.client import AIProviderClient, ChatMessage, ToolCallRequest
from app.assistant.sanitize import scrub_secrets
from app.assistant.tools import (
    PROPOSE_CHANGE_PLAN_TOOL,
    READ_ONLY_TOOLS,
    ReadOnlyToolError,
    ToolDispatcher,
    ToolSchema,
)
from app.changes.service import ChangeService
from app.core.errors import AppError, AutoModeRequiresAcknowledgmentError, ChangeValidationError
from app.models import (
    AssistantMessage,
    AssistantMessageRole,
    AssistantSession,
    AssistantSessionMode,
    ChangePlanSource,
    ChangeType,
)
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.provider_profiles import ProviderProfileRepository
from app.services.provider_profiles import ProviderKeyVault

_MAX_TOOL_ROUNDS_PER_TURN = 5


# Rough characters-per-token ratio. Counting exactly would mean shipping a
# tokenizer per model family; this is a deliberate approximation used only to
# decide when to drop the oldest turns, so erring small just trims earlier.
_CHARS_PER_TOKEN = 4


def _trim_to_context_limit(
    history: list[ChatMessage], limit_tokens: int | None
) -> list[ChatMessage]:
    """Drops the oldest turns until the conversation fits the profile's limit.

    The system message is never dropped, and the retained window never starts
    on a tool message -- an orphaned tool result whose announcing assistant
    turn was trimmed away is exactly what the chat contract rejects.
    """
    if limit_tokens is None or not history:
        return history
    budget = limit_tokens * _CHARS_PER_TOKEN
    system, rest = history[0], history[1:]
    kept: list[ChatMessage] = []
    used = len(system.content)
    for message in reversed(rest):
        cost = len(message.content)
        if used + cost > budget:
            break
        used += cost
        kept.append(message)
    kept.reverse()
    while kept and kept[0].role == "tool":
        kept.pop(0)
    return [system, *kept]


def _announced_tool_calls(calls: list[ToolCallRequest]) -> list[dict[str, object]]:
    """Storage shape for the tool calls one assistant turn announced."""
    return [{"id": call.id, "name": call.name, "arguments": call.arguments} for call in calls]


def _to_openai_tool_calls(announced: list[dict[str, object]]) -> list[dict[str, object]]:
    """Storage shape -> the wire shape the chat contract expects back."""
    return [
        {
            "id": call.get("id", ""),
            "type": "function",
            "function": {
                "name": call.get("name", ""),
                "arguments": json.dumps(call.get("arguments", {})),
            },
        }
        for call in announced
    ]


@dataclass(frozen=True, slots=True)
class AssistantEvent:
    type: Literal["token", "tool_call", "tool_result", "change_plan_proposed", "done", "error"]
    content: str | None = None
    tool_name: str | None = None
    tool_payload: dict[str, object] | None = None
    error_code: str | None = None


class AssistantChatService:
    def __init__(
        self,
        session: Session,
        *,
        provider_client: AIProviderClient,
        sessions: AssistantSessionRepository,
        messages: AssistantMessageRepository,
        profiles: ProviderProfileRepository,
        vault: ProviderKeyVault,
        tools: ToolDispatcher,
        changes: ChangeService | None = None,
    ) -> None:
        self._session = session
        self._provider_client = provider_client
        self._sessions = sessions
        self._messages = messages
        self._profiles = profiles
        self._vault = vault
        self._tools = tools
        self._changes = changes

    async def handle_user_message(
        self, session_id: UUID, content: str
    ) -> AsyncIterator[AssistantEvent]:
        chat_session = self._sessions.get(session_id)
        profile = self._profiles.get(chat_session.provider_profile_id)
        material = self._vault.decrypt(profile)

        self._messages.add(session_id=session_id, role=AssistantMessageRole.USER, content=content)
        self._session.commit()

        history = _trim_to_context_limit(
            self._build_history(session_id), profile.context_limit_override
        )
        tool_schemas: list[ToolSchema] | None = (
            list(READ_ONLY_TOOLS) if profile.supports_tool_calling else None
        )
        if tool_schemas is not None and self._changes is not None:
            tool_schemas = [*tool_schemas, PROPOSE_CHANGE_PLAN_TOOL]

        for _round in range(_MAX_TOOL_ROUNDS_PER_TURN):
            reply_text = ""
            pending_tool_calls: list[ToolCallRequest] = []
            async for chunk in self._provider_client.stream_chat(
                base_url=profile.base_url,
                api_key=material.api_key,
                model_id=profile.model_id,
                messages=history,
                tools=tool_schemas,
            ):
                if chunk.type == "token" and chunk.content:
                    reply_text += chunk.content
                    yield AssistantEvent(type="token", content=chunk.content)
                elif chunk.type == "tool_call" and chunk.tool_call is not None:
                    pending_tool_calls.append(chunk.tool_call)

            # Persisted even when reply_text is empty, as long as tool calls
            # were made: the tool messages below are only valid in a replayed
            # conversation if the assistant turn that announced them is there
            # too.
            if reply_text or pending_tool_calls:
                announced = _announced_tool_calls(pending_tool_calls)
                self._messages.add(
                    session_id=session_id,
                    role=AssistantMessageRole.ASSISTANT,
                    content=reply_text,
                    tool_calls={"calls": announced} if announced else None,
                )
                self._session.commit()
                history.append(
                    ChatMessage(
                        role="assistant",
                        content=reply_text,
                        tool_calls=_to_openai_tool_calls(announced) if announced else None,
                    )
                )

            if not pending_tool_calls:
                yield AssistantEvent(type="done")
                return

            for call in pending_tool_calls:
                yield AssistantEvent(
                    type="tool_call", tool_name=call.name, tool_payload=call.arguments
                )
                payload: dict[str, object]
                event_type: Literal["tool_result", "change_plan_proposed"] = "tool_result"
                changes = self._changes
                if call.name == PROPOSE_CHANGE_PLAN_TOOL.name and changes is not None:
                    payload = self._propose_change_plan(changes, call.arguments)
                    if "plan_id" in payload:
                        event_type = "change_plan_proposed"
                else:
                    try:
                        result = self._tools.dispatch(call.name, call.arguments)
                        payload = cast("dict[str, object]", scrub_secrets(result.payload))
                    except ReadOnlyToolError as exc:
                        payload = {"error": str(exc)}
                yield AssistantEvent(type=event_type, tool_name=call.name, tool_payload=payload)
                encoded_payload = json.dumps(payload)
                self._messages.add(
                    session_id=session_id,
                    role=AssistantMessageRole.TOOL,
                    content=encoded_payload,
                    tool_calls={"tool_call_id": call.id},
                    tool_results=payload,
                )
                self._session.commit()
                history.append(
                    ChatMessage(role="tool", content=encoded_payload, tool_call_id=call.id)
                )

        yield AssistantEvent(
            type="error",
            error_code="tool_round_limit_exceeded",
            content="The assistant made too many tool calls in one turn and was stopped.",
        )

    @staticmethod
    def _propose_change_plan(
        changes: ChangeService, arguments: dict[str, object]
    ) -> dict[str, object]:
        try:
            device_id = UUID(str(arguments["device_id"]))
            change_type = ChangeType(str(arguments["change_type"]))
            target = str(arguments["target"])
            desired_value = str(arguments["desired_value"])
        except (KeyError, ValueError) as exc:
            return {"error": f"Malformed change plan proposal: {exc}"}
        try:
            plan = changes.preview(
                device_id=device_id,
                change_type=change_type,
                target=target,
                desired_value=desired_value,
                source=ChangePlanSource.AI_GENERATED,
            )
        except AppError as exc:
            payload: dict[str, object] = {"error": str(exc)}
            if isinstance(exc, ChangeValidationError):
                payload["issues"] = exc.details.get("issues", [])
            return payload
        return {
            "plan_id": str(plan.id),
            "status": plan.status.value,
            "risk": plan.risk.value,
            "safety_level": plan.safety_level.value,
            "steps": [
                {
                    "target": s.target,
                    "desired_value": s.desired_value,
                    "rendered_commands": s.rendered_commands,
                }
                for s in plan.steps
            ],
        }

    @staticmethod
    def _replay(message: AssistantMessage) -> ChatMessage:
        stored_calls = message.tool_calls or {}
        if message.role is AssistantMessageRole.TOOL:
            tool_call_id = stored_calls.get("tool_call_id")
            return ChatMessage(
                role="tool",
                content=message.content,
                tool_call_id=str(tool_call_id) if tool_call_id is not None else None,
            )
        if message.role is AssistantMessageRole.ASSISTANT:
            announced = cast("list[dict[str, object]]", stored_calls.get("calls", []))
            return ChatMessage(
                role="assistant",
                content=message.content,
                tool_calls=_to_openai_tool_calls(announced) if announced else None,
            )
        return ChatMessage(role=message.role.value, content=message.content)

    def _build_history(self, session_id: UUID) -> list[ChatMessage]:
        stored = self._messages.list_for_session(session_id)
        system = ChatMessage(
            role="system",
            content=(
                "You are a read-only network assistant. You can inspect "
                "registered devices with the provided tools and propose a "
                "Change Plan with propose_change_plan, but you can never "
                "apply anything yourself -- a human always reviews and "
                "confirms every change. When you suggest a command for a "
                "human to run in a device's console terminal, always put "
                "it in a fenced code block (```) by itself, with no other "
                "text inside the fence."
            ),
        )
        return [system, *(self._replay(m) for m in stored)]

    def set_mode(
        self, session_id: UUID, mode: AssistantSessionMode, *, risk_acknowledged: bool
    ) -> AssistantSession:
        chat_session = self._sessions.get(session_id, for_update=True)
        if mode is AssistantSessionMode.AUTO and not risk_acknowledged:
            raise AutoModeRequiresAcknowledgmentError()
        self._sessions.set_mode(chat_session, mode)
        self._session.commit()
        return chat_session
