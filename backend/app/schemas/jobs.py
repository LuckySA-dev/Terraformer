from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.models import JobState, JobType
from app.schemas.common import APIModel


class JobView(APIModel):
    id: UUID
    type: JobType
    state: JobState
    device_id: UUID | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

