from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.models import EventSeverity
from app.schemas.common import APIModel


class EventView(APIModel):
    id: UUID
    device_id: UUID | None
    job_id: UUID | None
    event_type: str
    severity: EventSeverity
    message: str
    details: dict[str, Any]
    created_at: datetime

