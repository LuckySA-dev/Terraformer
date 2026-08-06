from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.models import DeviceStatus, SafetyLevel, SSHCompatibility, Vendor
from app.schemas.common import APIModel

_HOST = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$")


class DeviceConnectionFields(APIModel):
    management_address: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65_535)
    vendor: Vendor
    credential_profile_id: UUID
    ssh_compatibility: SSHCompatibility = SSHCompatibility.MODERN
    group1_risk_acknowledged: bool = False
    host_key_candidate_id: UUID | None = None

    @field_validator("management_address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        value = value.strip()
        if not _HOST.fullmatch(value) or ".." in value:
            raise ValueError("management_address must be an IP address or DNS hostname")
        return value.lower()


class DeviceCreate(DeviceConnectionFields):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class DeviceUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    management_address: str | None = Field(default=None, min_length=1, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65_535)
    vendor: Vendor | None = None
    credential_profile_id: UUID | None = None
    ssh_compatibility: SSHCompatibility | None = None
    group1_risk_acknowledged: bool = False
    host_key_candidate_id: UUID | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> DeviceUpdate:
        null_fields = [
            name for name in self.model_fields_set if getattr(self, name, None) is None
        ]
        if null_fields:
            raise ValueError(f"patch fields cannot be null: {', '.join(sorted(null_fields))}")
        return self

    @field_validator("management_address")
    @classmethod
    def validate_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not _HOST.fullmatch(value) or ".." in value:
            raise ValueError("management_address must be an IP address or DNS hostname")
        return value


class CapabilityView(APIModel):
    name: str
    supported: bool
    safety_level: SafetyLevel


class DeviceView(APIModel):
    id: UUID
    name: str
    management_address: str
    port: int
    vendor: Vendor
    ssh_compatibility: SSHCompatibility
    status: DeviceStatus
    credential_profile_id: UUID
    facts: dict[str, Any]
    capabilities: list[CapabilityView]
    last_seen_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class ConnectionTestView(APIModel):
    reachable: bool
    driver: str
    message: str
    latency_ms: int


class FactsView(APIModel):
    device_id: UUID
    facts: dict[str, Any]
    last_seen_at: datetime | None


class InterfaceView(APIModel):
    id: UUID
    device_id: UUID
    name: str
    description: str | None
    admin_up: bool | None
    oper_up: bool | None
    mac_address: str | None
    ipv4_addresses: list[str]
    speed_mbps: int | None
    created_at: datetime
    updated_at: datetime


class NeighborView(APIModel):
    id: UUID
    device_id: UUID
    protocol: Literal["cdp", "lldp"]
    local_interface: str
    remote_device_name: str
    remote_interface: str
    management_address: str | None
    platform: str | None
    created_at: datetime
    updated_at: datetime
