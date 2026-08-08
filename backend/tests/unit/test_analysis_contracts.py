from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import (
    AnalysisBackendUnavailableError,
    AnalysisDisabledByPolicyError,
    AnalysisNoConfigsError,
    AnalysisSnapshotExpiredError,
    AnalysisTooManyDevicesError,
    AnalysisUnavailableError,
)
from app.models import AnalysisStatus, ExclusionReason, FindingCategory, JobType


def test_analysis_is_disabled_unless_explicitly_enabled() -> None:
    """The kill switch must default off, like TELNET_ENABLED.

    Checks the class default directly rather than the shared `settings`
    fixture: that fixture deliberately sets analysis_enabled=True so the rest
    of the suite can exercise the feature without repeating the override in
    every test.
    """
    assert Settings.model_fields["analysis_enabled"].default is False


def test_analysis_bounds_have_conservative_defaults(settings: Settings) -> None:
    assert settings.analysis_max_devices == 200
    assert settings.analysis_max_findings == 1000
    assert settings.analysis_retained_snapshots == 10


def test_no_unenforced_timeout_setting_is_offered() -> None:
    """pybatfish exposes no timeout knob, so neither may Settings.

    A configurable timeout that nothing reads would claim a protection the
    feature does not have.
    """
    assert not [
        name for name in Settings.model_fields if name.startswith("analysis_") and "timeout" in name
    ]


@pytest.mark.parametrize(
    ("error_type", "code", "status_code"),
    [
        (AnalysisDisabledByPolicyError, "analysis_disabled_by_policy", 403),
        (AnalysisUnavailableError, "analysis_unavailable", 503),
        (AnalysisBackendUnavailableError, "analysis_backend_unavailable", 503),
        (AnalysisNoConfigsError, "analysis_no_configs", 422),
        (AnalysisSnapshotExpiredError, "analysis_snapshot_expired", 409),
        (AnalysisTooManyDevicesError, "analysis_too_many_devices", 422),
    ],
)
def test_analysis_errors_are_typed_and_stable(
    error_type: type[Exception], code: str, status_code: int
) -> None:
    error = error_type()
    assert error.code == code  # type: ignore[attr-defined]
    assert error.status_code == status_code  # type: ignore[attr-defined]
    assert error.message  # type: ignore[attr-defined]


def test_analysis_enums_cover_the_designed_values() -> None:
    assert {item.value for item in AnalysisStatus} == {
        "pending",
        "parsing",
        "ready",
        "failed",
        "expired",
    }
    assert {item.value for item in ExclusionReason} == {
        "no_snapshot",
        "unsupported_vendor",
    }
    assert {item.value for item in FindingCategory} == {
        "parse_warning",
        "undefined_reference",
        "unused_structure",
        "topology_drift",
    }
    assert JobType.ANALYZE_NETWORK.value == "analyze_network"
