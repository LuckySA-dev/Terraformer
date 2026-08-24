from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.assistant.client import AIProviderClient, ChatMessage, ToolCallRequest
from app.assistant.sanitize import scrub_secrets
from app.assistant.tools import READ_ONLY_TOOLS, ReadOnlyToolError, ToolDispatcher
from app.core.errors import AutoModeRequiresAcknowledgmentError
from app.models import AssistantMessageRole, AssistantSession, AssistantSessionMode
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.provider_profiles import ProviderProfileRepository
from app.services.provider_profiles import ProviderKeyVault

_MAX_TOOL_ROUNDS_PER_TURN = 5


@dataclass(frozen=True, slots=True)
class AssistantEvent:
    type: Literal["token", "tool_call", "tool_result", "done", "error"]
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
    ) -> None:
        self._session = session
        self._provider_client = provider_client
        self._sessions = sessions
        self._messages = messages
        self._profiles = profiles
        self._vault = vault
        self._tools = tools

    async def handle_user_message(
        self, session_id: UUID, content: str
    ) -> AsyncIterator[AssistantEvent]:
        chat_session = self._sessions.get(session_id)
        profile = self._profiles.get(chat_session.provider_profile_id)
        material = self._vault.decrypt(profile)

        self._messages.add(session_id=session_id, role=AssistantMessageRole.USER, content=content)
        self._session.commit()

        history = self._build_history(session_id)
        tool_schemas = list(READ_ONLY_TOOLS) if profile.supports_tool_calling else None

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

            if reply_text:
                self._messages.add(
                    session_id=session_id, role=AssistantMessageRole.ASSISTANT, content=reply_text
                )
                self._session.commit()
                history.append(ChatMessage(role="assistant", content=reply_text))

            if not pending_tool_calls:
                yield AssistantEvent(type="done")
                return

            for call in pending_tool_calls:
                yield AssistantEvent(
                    type="tool_call", tool_name=call.name, tool_payload=call.arguments
                )
                payload: dict[str, object]
                try:
                    result = self._tools.dispatch(call.name, call.arguments)
                    payload = cast("dict[str, object]", scrub_secrets(result.payload))
                except ReadOnlyToolError as exc:
                    payload = {"error": str(exc)}
                yield AssistantEvent(type="tool_result", tool_name=call.name, tool_payload=payload)
                encoded_payload = json.dumps(payload)
                self._messages.add(
                    session_id=session_id,
                    role=AssistantMessageRole.TOOL,
                    content=encoded_payload,
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
        return [system, *(ChatMessage(role=m.role.value, content=m.content) for m in stored)]

    def set_mode(
        self, session_id: UUID, mode: AssistantSessionMode, *, risk_acknowledged: bool
    ) -> AssistantSession:
        chat_session = self._sessions.get(session_id, for_update=True)
        if mode is AssistantSessionMode.AUTO and not risk_acknowledged:
            raise AutoModeRequiresAcknowledgmentError()
        self._sessions.set_mode(chat_session, mode)
        self._session.commit()
        return chat_session
