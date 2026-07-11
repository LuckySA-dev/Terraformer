from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ErrorBody(APIModel):
    code: str
    message: str
    details: dict[str, Any]
    request_id: str


class ErrorResponse(APIModel):
    error: ErrorBody

