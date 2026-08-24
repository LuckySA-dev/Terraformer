from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from app.schemas.common import APIModel


class ProviderProfileCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    model_id: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, max_length=4_096)
    context_limit_override: int | None = Field(default=None, ge=1, le=10_000_000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return value


class ProviderProfileUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, max_length=4_096)
    clear_api_key: bool = False
    context_limit_override: int | None = Field(default=None, ge=1, le=10_000_000)


class ProviderProfileView(APIModel):
    id: UUID
    name: str
    base_url: str
    model_id: str
    has_api_key: bool
    context_limit_override: int | None
    supports_streaming: bool
    supports_tool_calling: bool
    created_at: datetime
    updated_at: datetime
