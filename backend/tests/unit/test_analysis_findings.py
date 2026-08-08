from __future__ import annotations

from uuid import uuid4

from app.analysis.client import RawFinding
from app.analysis.findings import DETAIL_MAX_LENGTH, to_findings
from app.models import EventSeverity, FindingCategory


def _raw(detail: str, hostname: str | None = "sw1") -> RawFinding:
    return RawFinding(
        category=FindingCategory.PARSE_WARNING,
        hostname=hostname,
        structure_type=None,
        structure_name=None,
        detail=detail,
        line_number=12,
    )


def test_finding_detail_is_sanitized() -> None:
    """Batfish quotes the offending configuration line in parse warnings."""
    raw = _raw("unrecognized: snmp-server community s3cr3t-community RO")

    prepared, _ = to_findings([raw], hostname_to_device={}, max_findings=100)

    assert "s3cr3t-community" not in prepared[0].detail
    assert "[REDACTED]" in prepared[0].detail


def test_finding_detail_is_length_capped() -> None:
    prepared, _ = to_findings(
        [_raw("x" * (DETAIL_MAX_LENGTH * 3))], hostname_to_device={}, max_findings=100
    )

    assert len(prepared[0].detail) <= DETAIL_MAX_LENGTH


def test_hostname_is_resolved_back_to_a_device() -> None:
    device_id = uuid4()

    prepared, _ = to_findings(
        [_raw("something", hostname="sw1")],
        hostname_to_device={"sw1": device_id},
        max_findings=100,
    )

    assert prepared[0].device_id == device_id


def test_unmatched_hostname_yields_a_network_wide_finding() -> None:
    prepared, _ = to_findings(
        [_raw("something", hostname="not-a-known-node")],
        hostname_to_device={"sw1": uuid4()},
        max_findings=100,
    )

    assert prepared[0].device_id is None


def test_findings_are_capped_and_truncation_is_reported() -> None:
    raw = [_raw(f"issue {index}") for index in range(10)]

    prepared, truncated = to_findings(raw, hostname_to_device={}, max_findings=4)

    assert len(prepared) == 4
    assert truncated is True


def test_no_truncation_flag_when_under_the_cap() -> None:
    prepared, truncated = to_findings(
        [_raw("only one")], hostname_to_device={}, max_findings=4
    )

    assert len(prepared) == 1
    assert truncated is False


def test_parse_warnings_are_errors_and_unused_structures_are_informational() -> None:
    warning = RawFinding(
        FindingCategory.PARSE_WARNING, "sw1", None, None, "cannot parse", 1
    )
    unused = RawFinding(
        FindingCategory.UNUSED_STRUCTURE, "sw1", "acl", "OLD_ACL", "unused", 2
    )

    prepared, _ = to_findings([warning, unused], hostname_to_device={}, max_findings=10)

    by_category = {item.category: item.severity for item in prepared}
    assert by_category[FindingCategory.PARSE_WARNING] is EventSeverity.ERROR
    assert by_category[FindingCategory.UNUSED_STRUCTURE] is EventSeverity.INFO
