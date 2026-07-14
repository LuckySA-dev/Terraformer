from __future__ import annotations

from ipaddress import IPv4Address
from uuid import UUID

from pydantic import model_validator

from app.drivers import DiagnosticAction
from app.schemas.common import APIModel


class DiagnosticRequest(APIModel):
    device_id: UUID
    action: DiagnosticAction
    target: IPv4Address | None = None

    @model_validator(mode="after")
    def validate_target(self) -> DiagnosticRequest:
        requires_target = self.action in {
            DiagnosticAction.PING,
            DiagnosticAction.TRACEROUTE,
        }
        if requires_target != (self.target is not None):
            raise ValueError("Target is required only for ping and traceroute")
        if self.target is not None and (
            self.target.is_loopback
            or self.target.is_link_local
            or self.target.is_multicast
            or self.target.is_unspecified
            or self.target.is_reserved
        ):
            raise ValueError("Target must be an exact routable unicast IPv4 address")
        return self


class DiagnosticJobInput(APIModel):
    action: DiagnosticAction
    target: IPv4Address | None = None


class DiagnosticResult(APIModel):
    device_id: UUID
    action: DiagnosticAction
    target: str | None = None
    output: str
    truncated: bool
