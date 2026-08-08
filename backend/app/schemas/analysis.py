from __future__ import annotations

from datetime import datetime
from uuid import UUID

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
