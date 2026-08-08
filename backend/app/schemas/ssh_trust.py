from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models import SSHCompatibility, Vendor
from app.schemas.common import APIModel
from app.schemas.devices import DeviceConnectionFields


class HostKeyCandidateRequest(DeviceConnectionFields):
    pass


class HostKeyRepinRequest(APIModel):
    host_key_candidate_id: UUID


class HostKeyCandidateView(APIModel):
    id: UUID
    algorithm: str = Field(max_length=64)
    fingerprint: str = Field(max_length=128)
    expires_at: datetime


class DeviceSSHHostKeyView(APIModel):
    device_id: UUID
    algorithm: str
    fingerprint: str
    confirmed_at: datetime
    confirmed_by: str


class HostKeyCandidateBinding(APIModel):
    management_address: str
    port: int
    vendor: Vendor
    credential_profile_id: UUID
    ssh_compatibility: SSHCompatibility
