from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from app.schemas.common import APIModel


class CredentialProfileCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    username: SecretStr = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=4_096)
    enable_password: SecretStr | None = Field(default=None, max_length=4_096)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class CredentialProfileUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    username: SecretStr | None = Field(default=None, min_length=1, max_length=255)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=4_096)
    enable_password: SecretStr | None = Field(default=None, max_length=4_096)
    clear_enable_password: bool = False


class CredentialProfileView(APIModel):
    id: UUID
    name: str
    has_username: bool
    has_password: bool
    has_enable_password: bool
    created_at: datetime
    updated_at: datetime

