from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.models import AssistantMessageRole, AssistantSessionMode
from app.schemas.common import APIModel


class AssistantSessionCreate(APIModel):
    provider_profile_id: UUID


class AssistantSessionView(APIModel):
    id: UUID
    provider_profile_id: UUID
    mode: AssistantSessionMode
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
