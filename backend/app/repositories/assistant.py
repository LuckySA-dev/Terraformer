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


class AssistantSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[AssistantSession]:
        statement = select(AssistantSession).order_by(AssistantSession.created_at.desc())
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

    def add(self, *, provider_profile_id: UUID) -> AssistantSession:
        chat_session = AssistantSession(provider_profile_id=provider_profile_id)
        self._session.add(chat_session)
        self._session.flush()
        return chat_session

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
