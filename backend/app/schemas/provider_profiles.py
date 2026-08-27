from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from app.models import ProviderType
from app.schemas.common import APIModel


class ProviderProfileCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    provider_type: ProviderType = ProviderType.OPENAI_COMPATIBLE
    base_url: str = Field(min_length=1, max_length=500)
    api_key: SecretStr | None = Field(default=None, max_length=4_096)

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
    provider_type: ProviderType | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: SecretStr | None = Field(default=None, max_length=4_096)
    clear_api_key: bool = False


class ProviderProfileView(APIModel):
    id: UUID
    name: str
    provider_type: ProviderType
    base_url: str
    has_api_key: bool
    created_at: datetime
    updated_at: datetime
