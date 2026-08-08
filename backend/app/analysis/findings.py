"""Map raw backend rows to persisted findings.

Every detail string is sanitized and length-capped here. Batfish quotes the
offending configuration line in its parse warnings, so although the
configuration sent to it is already sanitized, this is the last point before a
finding is stored and is treated as a control rather than a formality.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.analysis.client import RawFinding
from app.core.logging import sanitize_text
from app.models import EventSeverity, FindingCategory

DETAIL_MAX_LENGTH = 2_000

_SEVERITY_BY_CATEGORY = {
    FindingCategory.PARSE_WARNING: EventSeverity.ERROR,
    FindingCategory.UNDEFINED_REFERENCE: EventSeverity.WARNING,
    FindingCategory.UNUSED_STRUCTURE: EventSeverity.INFO,
    FindingCategory.TOPOLOGY_DRIFT: EventSeverity.WARNING,
}


@dataclass(frozen=True, slots=True)
class PreparedFinding:
    category: FindingCategory
    severity: EventSeverity
    device_id: UUID | None
    structure_type: str | None
    structure_name: str | None
    detail: str
    line_number: int | None


def to_findings(
    raw: Sequence[RawFinding],
    *,
    hostname_to_device: Mapping[str, UUID],
    max_findings: int,
) -> tuple[list[PreparedFinding], bool]:
    truncated = len(raw) > max_findings
    prepared = [
        PreparedFinding(
            category=item.category,
            severity=_SEVERITY_BY_CATEGORY[item.category],
            device_id=(
                hostname_to_device.get(item.hostname.strip().lower())
                if item.hostname is not None
                else None
            ),
            structure_type=_clip(item.structure_type, 100),
            structure_name=_clip(item.structure_name, 255),
            detail=sanitize_text(item.detail)[:DETAIL_MAX_LENGTH],
            line_number=item.line_number,
        )
        for item in raw[:max_findings]
    ]
    return prepared, truncated


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return sanitize_text(value)[:limit] or None
