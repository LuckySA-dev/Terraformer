from __future__ import annotations

from pydantic import Field, SecretStr

from app.schemas.common import APIModel


class SetupStatus(APIModel):
    configured: bool


class MasterPasswordRequest(APIModel):
    master_password: SecretStr = Field(min_length=12, max_length=1_024)


class SessionStatus(APIModel):
    authenticated: bool

