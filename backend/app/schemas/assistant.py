from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.models import AssistantMessageRole, AssistantSessionMode
from app.schemas.common import APIModel


class AssistantSessionCreate(APIModel):
    provider_profile_id: UUID
    model_id: str = Field(min_length=1, max_length=200)
    device_id: UUID | None = None
    # Empty means every registered device. Bounded so one request cannot push
    # an unreasonable device list into the model's system prompt.
    scope_device_ids: list[UUID] = Field(default_factory=list[UUID], max_length=50)


class AssistantSessionUpdate(APIModel):
    """Switches an existing conversation to a different provider/model.

    `scope_device_ids` is optional so the model picker and the device-scope
    picker can each PATCH without clobbering the other's field.
    """

    provider_profile_id: UUID | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    scope_device_ids: list[UUID] | None = Field(default=None, max_length=50)


class AssistantSessionView(APIModel):
    id: UUID
    provider_profile_id: UUID
    model_id: str
    device_id: UUID | None
    scope_device_ids: list[UUID]
    mode: AssistantSessionMode
    supports_streaming: bool
    supports_tool_calling: bool
    auto_apply_count: int
    created_at: datetime
    updated_at: datetime


class AssistantMessageView(APIModel):
    id: UUID
    session_id: UUID
    role: AssistantMessageRole
    content: str
    tool_calls: dict[str, Any] | None
    tool_results: dict[str, Any] | None
    created_at: datetime


class SetAssistantModeRequest(APIModel):
    mode: AssistantSessionMode
    risk_acknowledged: bool = Field(default=False)
