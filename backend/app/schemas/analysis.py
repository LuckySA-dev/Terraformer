from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.models import AnalysisStatus, EventSeverity, ExclusionReason, FindingCategory
from app.schemas.common import APIModel


class ExclusionView(APIModel):
    reason: ExclusionReason
    count: int


class CompletenessView(APIModel):
    """Mandatory on every result surface.

    Batfish answers only from the configurations it was given, so an incomplete
    set produces confident but unreliable answers. Reachability accuracy also
    depends on observed_link_count: without a layer-1 topology Batfish must
    infer adjacency from addressing, which is weak on a switched network.
    """

    registered_device_count: int
    analysed_device_count: int
    observed_link_count: int
    exclusions: list[ExclusionView]
    oldest_config_at: datetime | None
    newest_config_at: datetime | None


class AnalysisSnapshotView(APIModel):
    id: UUID
    status: AnalysisStatus
    evidence: str = "INFERRED"
    parse_warning_count: int
    findings_truncated: bool
    failure_code: str | None
    completeness: CompletenessView
    created_at: datetime
    updated_at: datetime


class FindingView(APIModel):
    id: UUID
    category: FindingCategory
    severity: EventSeverity
    device_id: UUID | None
    structure_type: str | None
    structure_name: str | None
    detail: str
    line_number: int | None
    evidence: str = "INFERRED"


class _ExactIPv4Destination(APIModel):
    """Exact routable unicast IPv4 only.

    Mirrors DiagnosticRequest.validate_target in app/schemas/diagnostics.py:
    the field type itself does the format check (CIDR, hostnames and IPv6 are
    rejected by Pydantic before validators run), and this model_validator
    additionally rejects loopback/link-local/multicast/unspecified/reserved
    destinations, which a Batfish query is never meaningfully asked about.
    """

    destination_ip: IPv4Address

    @model_validator(mode="after")
    def validate_destination(self) -> _ExactIPv4Destination:
        if (
            self.destination_ip.is_loopback
            or self.destination_ip.is_link_local
            or self.destination_ip.is_multicast
            or self.destination_ip.is_unspecified
            or self.destination_ip.is_reserved
        ):
            raise ValueError("destination_ip must be an exact routable unicast IPv4 address")
        return self


class PathCheckRequest(_ExactIPv4Destination):
    source_device_id: UUID


class FilterCheckRequest(_ExactIPv4Destination):
    device_id: UUID
    filter_name: str = Field(min_length=1, max_length=255)
    protocol: Literal["tcp", "udp", "icmp"] = "tcp"
    destination_port: int | None = Field(default=None, ge=1, le=65_535)


class TraceHopView(APIModel):
    hostname: str
    action: str
    detail: str


class PathCheckView(APIModel):
    disposition: str
    hops: list[TraceHopView]
    evidence: str = "INFERRED"
    completeness: CompletenessView


class FilterCheckView(APIModel):
    permitted: bool
    matched_line_index: int | None
    matched_line: str | None
    evidence: str = "INFERRED"
    completeness: CompletenessView
