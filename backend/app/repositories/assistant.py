from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.time import utc_now
from app.models import (
    AssistantMessage,
    AssistantMessageRole,
    AssistantSession,
    AssistantSessionMode,
)

# Auto mode is the operator accepting that changes land without a per-change
# prompt. This cap is what keeps "accepted the risk" from meaning "unbounded".
# It is counted in the database rather than the browser so that reloading the
# page cannot silently hand out a fresh allowance.
MAX_AUTO_APPLIES_PER_SESSION = 5


class AssistantSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(
        self, *, device_id: UUID | None = None, device_scoped: bool = False
    ) -> list[AssistantSession]:
        """List sessions, optionally narrowed to one device's own chats.

        `device_scoped` distinguishes "every session" from "the workspace-wide
        sessions only" -- without it, `device_id=None` could not ask for the
        unscoped chats without also returning every device's chat.
        """
        statement = select(AssistantSession).order_by(AssistantSession.created_at.desc())
        if device_scoped:
            statement = statement.where(AssistantSession.device_id == device_id)
        return list(self._session.scalars(statement))

    def get(self, session_id: UUID, *, for_update: bool = False) -> AssistantSession:
        statement = select(AssistantSession).where(AssistantSession.id == session_id)
        if for_update:
            statement = statement.with_for_update()
        chat_session = self._session.scalar(statement)
        if chat_session is None:
            raise NotFoundError(
                "Assistant session not found",
                details={"resource": "assistant_session", "id": str(session_id)},
            )
        return chat_session

    def add(
        self,
        *,
        provider_profile_id: UUID,
        model_id: str,
        device_id: UUID | None = None,
        scope_device_ids: list[str] | None = None,
        context_limit_override: int | None = None,
        supports_streaming: bool = False,
        supports_tool_calling: bool = False,
    ) -> AssistantSession:
        chat_session = AssistantSession(
            provider_profile_id=provider_profile_id,
            model_id=model_id,
            device_id=device_id,
            scope_device_ids=scope_device_ids or [],
            context_limit_override=context_limit_override,
            supports_streaming=supports_streaming,
            supports_tool_calling=supports_tool_calling,
        )
        self._session.add(chat_session)
        self._session.flush()
        return chat_session

    def set_model(
        self,
        chat_session: AssistantSession,
        *,
        provider_profile_id: UUID,
        model_id: str,
        supports_streaming: bool,
        supports_tool_calling: bool,
    ) -> None:
        """Point an existing conversation at a different model.

        Capability flags are replaced, never merged: they were probed against
        the previous model and say nothing about this one. Mode and the Auto
        allowance are deliberately left alone -- switching model is not a fresh
        acceptance of risk, so it must not silently reset the count that bounds
        how many applies Auto mode still has.
        """
        chat_session.provider_profile_id = provider_profile_id
        chat_session.model_id = model_id
        chat_session.supports_streaming = supports_streaming
        chat_session.supports_tool_calling = supports_tool_calling
        self._session.flush()

    def set_scope(self, chat_session: AssistantSession, scope_device_ids: list[str]) -> None:
        """Replace which devices the conversation is about. Empty means all."""
        chat_session.scope_device_ids = scope_device_ids
        self._session.flush()

    def set_mode(self, chat_session: AssistantSession, mode: AssistantSessionMode) -> None:
        chat_session.mode = mode
        if mode is AssistantSessionMode.AUTO:
            chat_session.auto_mode_acknowledged_at = utc_now()
            chat_session.auto_apply_count = 0
        self._session.flush()

    def record_auto_apply(self, chat_session: AssistantSession) -> None:
        chat_session.auto_apply_count += 1
        self._session.flush()


class AssistantMessageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        session_id: UUID,
        role: AssistantMessageRole,
        content: str,
        tool_calls: dict[str, Any] | None = None,
        tool_results: dict[str, Any] | None = None,
    ) -> AssistantMessage:
        message = AssistantMessage(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_results=tool_results,
        )
        self._session.add(message)
        self._session.flush()
        return message

    def list_for_session(self, session_id: UUID) -> list[AssistantMessage]:
        statement = (
            select(AssistantMessage)
            .where(AssistantMessage.session_id == session_id)
            .order_by(AssistantMessage.created_at)
        )
        return list(self._session.scalars(statement))
