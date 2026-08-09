from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.models import ChangePlanStatus, ChangeRisk, ChangeType, SafetyLevel
from app.schemas.common import APIModel


class ChangePlanRequest(APIModel):
    device_id: UUID
    change_type: ChangeType
    target: str
    desired_value: str


class ChangeStepView(APIModel):
    id: UUID
    change_type: ChangeType
    target: str
    previous_value: str | None
    desired_value: str
    rendered_commands: str
    inverse_commands: str


class ChangePlanView(APIModel):
    id: UUID
    device_id: UUID
    status: ChangePlanStatus
    safety_level: SafetyLevel
    risk: ChangeRisk
    failure_code: str | None
    applied_at: datetime | None
    steps: list[ChangeStepView]
    created_at: datetime
    updated_at: datetime
