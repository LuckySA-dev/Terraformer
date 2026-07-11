from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import redact_value, sanitize_text
from app.models import Event, EventSeverity


class EventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        event_type: str,
        message: str,
        device_id: UUID | None = None,
        job_id: UUID | None = None,
        severity: EventSeverity = EventSeverity.INFO,
        details: dict[str, Any] | None = None,
    ) -> Event:
        sanitized_details = redact_value(details or {})
        if not isinstance(sanitized_details, dict):
            sanitized_details = {}
        event = Event(
            event_type=event_type,
            message=sanitize_text(message),
            device_id=device_id,
            job_id=job_id,
            severity=severity,
            details=sanitized_details,
        )
        self._session.add(event)
        self._session.flush()
        return event

    def list(
        self,
        *,
        device_id: UUID | None = None,
        job_id: UUID | None = None,
        limit: int = 100,
    ) -> list[Event]:
        statement = select(Event)
        if device_id is not None:
            statement = statement.where(Event.device_id == device_id)
        if job_id is not None:
            statement = statement.where(Event.job_id == job_id)
        statement = statement.order_by(Event.created_at.desc()).limit(limit)
        return list(self._session.scalars(statement))

