# Batfish Read-Only Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, read-only network analysis capability that answers four operator questions from the configuration snapshots the application already stores, without any write path to a device.

**Architecture:** A profile-gated Batfish container on an internal-only Docker network receives sanitized configuration text plus a layer-1 topology derived from stored CDP/LLDP records. An RQ job parses that set once and persists findings; interactive queries then run against the parsed snapshot in about a second. Every result is labelled `INFERRED` and carries a mandatory completeness disclosure.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, RQ, `pybatfish` (optional dependency, lazily imported), Docker Compose profiles, React + TypeScript + Vitest.

**Spec:** `docs/superpowers/specs/2026-08-08-batfish-read-only-analysis-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Only sanitized configuration leaves the database.** Configuration content reaches Batfish exclusively through `SnapshotService.get_sanitized_content()`. No new decryption path may be written.
- **Analysis is disabled by default.** `ANALYSIS_ENABLED` defaults to `False`. Every analysis endpoint fails closed when it is false.
- **Cisco IOS/IOS-XE only.** `Vendor.CISCO_IOSXE` is the sole supported vendor. Other vendors are recorded as exclusions, never silently dropped.
- **Batfish receives no secrets and no route to devices.** The `analysis` Docker network is `internal: true`. The container mounts no Compose secrets and publishes no host port.
- **Every result is labelled `INFERRED`.** Required by `docs/network-automation-final-plan.md` §6.
- **Completeness disclosure is mandatory** on every result surface, implemented in one shared component so a new surface cannot omit it.
- **All findings text passes `sanitize_text`** from `app.core.logging` before storage. Batfish quotes offending configuration lines in parse warnings.
- **Result copy must never assert a network is correct.** "No findings within the analysed scope" is permitted; "your network is healthy" is not.
- **Errors are typed `AppError` subclasses**, following `backend/app/core/errors.py`. No raw exception text or class name reaches a response or an event.
- **Limits are enforced bounds, not capacity claims.** Per spec §8.4, no document may describe this feature as supporting 200 devices or campus scale.
- **Test commands:**
  - Backend: `cd backend && .venv/Scripts/python.exe -m pytest --basetemp=<scratch> -q`
  - Backend lint/types: `.venv/Scripts/python.exe -m ruff check --no-cache .` then `.venv/Scripts/pyright.exe`
  - Frontend: `cd frontend && npm run typecheck && npm run lint && npm test -- --run`
  - `pytest` needs `--basetemp` pointed at a writable directory on this machine; the default temp root is not writable.

## File Structure

**Backend — created**

| File | Responsibility |
|---|---|
| `backend/app/analysis/__init__.py` | Public exports for the package |
| `backend/app/analysis/types.py` | Frozen dataclasses shared across the package; no Batfish or pandas types |
| `backend/app/analysis/snapshot_builder.py` | Assemble the sanitized configuration set, classify devices, derive layer-1 edges |
| `backend/app/analysis/client.py` | The only module that knows Batfish exists; lazy `pybatfish` import |
| `backend/app/analysis/findings.py` | Map raw Batfish rows to persisted findings; sanitize and cap |
| `backend/app/analysis/drift.py` | Compare stored CDP/LLDP against parsed interface and VLAN properties |
| `backend/app/analysis/service.py` | Orchestrates init and query; the only entry point the API and job use |
| `backend/app/repositories/analysis.py` | Persistence for the three analysis tables |
| `backend/app/schemas/analysis.py` | Request and response models |
| `backend/app/api/analysis.py` | REST endpoints |
| `backend/migrations/versions/20260808_0008_analysis_snapshots.py` | Three tables |

**Backend — modified**

| File | Change |
|---|---|
| `backend/app/core/config.py` | `ANALYSIS_ENABLED`, `BATFISH_HOST`, `BATFISH_PORT`, timeouts, caps |
| `backend/app/core/errors.py` | Six analysis error classes |
| `backend/app/models/entities.py` | Three models plus three enums |
| `backend/app/models/__init__.py` | Export the new names |
| `backend/app/api/router.py` | Include the analysis router |
| `backend/app/jobs/tasks.py` | Dispatch `JobType.ANALYZE_NETWORK` |
| `backend/app/container.py` | `analysis_client` cached property |
| `backend/pyproject.toml` | `[project.optional-dependencies] analysis` |
| `backend/tests/fakes.py` | `FakeBatfishClient` |
| `backend/tests/conftest.py` | Wire the fake client into the test container |

**Deploy — created**

| File | Responsibility |
|---|---|
| `deploy/compose.analysis.yml` | Batfish service, `analysis` internal network |

**Frontend — created**

| File | Responsibility |
|---|---|
| `frontend/src/features/analysis/AnalysisPage.tsx` | Page shell and tabs |
| `frontend/src/features/analysis/CompletenessBanner.tsx` | The mandatory disclosure |
| `frontend/src/features/analysis/FindingsTab.tsx` | Persisted findings |
| `frontend/src/features/analysis/PathCheckTab.tsx` | Interactive traceroute |
| `frontend/src/features/analysis/FilterCheckTab.tsx` | Interactive ACL check |

**Frontend — modified**

| File | Change |
|---|---|
| `frontend/src/components/AppShell.tsx` | Add the `analysis` view |
| `frontend/src/types/api.ts` | Analysis types |
| `frontend/src/api/network.ts` | Analysis API methods |

---

## Task 1: Settings, errors, data model, and migration

Establishes every contract later tasks import. No behaviour yet, so it is fully testable on its own, and the kill-switch default is a security property that deserves its own review gate.

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/errors.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/20260808_0008_analysis_snapshots.py`
- Test: `backend/tests/unit/test_analysis_contracts.py`
- Test: `backend/tests/integration/test_migrations.py` (extend)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Settings.analysis_enabled: bool = False`, `Settings.batfish_host: str = "batfish"`, `Settings.batfish_port: int = 9996`, `Settings.analysis_query_timeout_seconds: float = 30.0`, `Settings.analysis_parse_timeout_seconds: float = 600.0`, `Settings.analysis_max_devices: int = 200`, `Settings.analysis_max_findings: int = 1000`, `Settings.analysis_retained_snapshots: int = 10`
  - Errors: `AnalysisDisabledByPolicyError` (403, `analysis_disabled_by_policy`), `AnalysisUnavailableError` (503, `analysis_unavailable`), `AnalysisBackendUnavailableError` (503, `analysis_backend_unavailable`), `AnalysisNoConfigsError` (422, `analysis_no_configs`), `AnalysisSnapshotExpiredError` (409, `analysis_snapshot_expired`), `AnalysisTimeoutError` (504, `analysis_timeout`)
  - Enums: `AnalysisStatus`, `ExclusionReason`, `FindingCategory`
  - Models: `AnalysisSnapshot`, `AnalysisSnapshotMember`, `AnalysisFinding`
  - `JobType.ANALYZE_NETWORK = "analyze_network"`

- [ ] **Step 1: Write the failing contract test**

Create `backend/tests/unit/test_analysis_contracts.py`:

```python
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import (
    AnalysisBackendUnavailableError,
    AnalysisDisabledByPolicyError,
    AnalysisNoConfigsError,
    AnalysisSnapshotExpiredError,
    AnalysisTimeoutError,
    AnalysisUnavailableError,
)
from app.models import AnalysisStatus, ExclusionReason, FindingCategory, JobType


def test_analysis_is_disabled_unless_explicitly_enabled(settings: Settings) -> None:
    """The kill switch must default off, like TELNET_ENABLED."""
    assert settings.analysis_enabled is False


def test_analysis_bounds_have_conservative_defaults(settings: Settings) -> None:
    assert settings.analysis_max_devices == 200
    assert settings.analysis_max_findings == 1000
    assert settings.analysis_retained_snapshots == 10
    assert settings.analysis_query_timeout_seconds == 30.0
    assert settings.analysis_parse_timeout_seconds == 600.0


@pytest.mark.parametrize(
    ("error_type", "code", "status_code"),
    [
        (AnalysisDisabledByPolicyError, "analysis_disabled_by_policy", 403),
        (AnalysisUnavailableError, "analysis_unavailable", 503),
        (AnalysisBackendUnavailableError, "analysis_backend_unavailable", 503),
        (AnalysisNoConfigsError, "analysis_no_configs", 422),
        (AnalysisSnapshotExpiredError, "analysis_snapshot_expired", 409),
        (AnalysisTimeoutError, "analysis_timeout", 504),
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
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_analysis_contracts.py -q --basetemp=<scratch>`
Expected: FAIL with `ImportError: cannot import name 'AnalysisBackendUnavailableError'`.

- [ ] **Step 3: Add the settings**

In `backend/app/core/config.py`, immediately after the `telnet_enabled` line:

```python
    # Read-only Batfish configuration analysis. Off by default: it requires an
    # extra container, and the documented resource floor assumes it is absent.
    analysis_enabled: bool = False
    batfish_host: str = "batfish"
    batfish_port: int = Field(default=9996, ge=1, le=65_535)
    analysis_query_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    analysis_parse_timeout_seconds: float = Field(default=600.0, gt=0, le=3600)
    # Enforced bounds that protect the host. They are not a claim that the
    # feature has been shown to work at this scale — see the design spec §8.4.
    analysis_max_devices: int = Field(default=200, ge=1, le=1000)
    analysis_max_findings: int = Field(default=1000, ge=1, le=100_000)
    analysis_retained_snapshots: int = Field(default=10, ge=1, le=100)
```

- [ ] **Step 4: Add the errors**

Append to `backend/app/core/errors.py`:

```python
class AnalysisDisabledByPolicyError(AppError):
    code = "analysis_disabled_by_policy"
    status_code = 403
    default_message = "Configuration analysis is disabled by server policy"


class AnalysisUnavailableError(AppError):
    code = "analysis_unavailable"
    status_code = 503
    default_message = "Configuration analysis support is not installed"


class AnalysisBackendUnavailableError(AppError):
    code = "analysis_backend_unavailable"
    status_code = 503
    default_message = "The analysis service is not reachable"


class AnalysisNoConfigsError(AppError):
    code = "analysis_no_configs"
    status_code = 422
    default_message = "No device has a configuration snapshot to analyse"


class AnalysisSnapshotExpiredError(ConflictError):
    code = "analysis_snapshot_expired"
    default_message = "The analysis snapshot is no longer loaded and must be re-parsed"


class AnalysisTimeoutError(AppError):
    code = "analysis_timeout"
    status_code = 504
    default_message = "The analysis query exceeded its time limit"
```

- [ ] **Step 5: Add the enums and models**

In `backend/app/models/entities.py`, after the `ConsoleTransport` class:

```python
class AnalysisStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    READY = "ready"
    FAILED = "failed"
    # The Batfish container lost the parsed snapshot, usually on restart.
    EXPIRED = "expired"


class ExclusionReason(StrEnum):
    NO_SNAPSHOT = "no_snapshot"
    UNSUPPORTED_VENDOR = "unsupported_vendor"


class FindingCategory(StrEnum):
    PARSE_WARNING = "parse_warning"
    UNDEFINED_REFERENCE = "undefined_reference"
    UNUSED_STRUCTURE = "unused_structure"
    TOPOLOGY_DRIFT = "topology_drift"
```

Add `ANALYZE_NETWORK = "analyze_network"` to `JobType`.

Then append the three models at the end of the file:

```python
class AnalysisSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One parse of the network's configuration set.

    The id is also the snapshot name inside Batfish, so a row can be located in
    the container without a second mapping.
    """

    __tablename__ = "analysis_snapshots"

    status: Mapped[AnalysisStatus] = mapped_column(
        enum_type(AnalysisStatus, "analysis_status"),
        nullable=False,
        default=AnalysisStatus.PENDING,
    )
    device_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observed_link_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oldest_config_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    newest_config_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parse_warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_code: Mapped[str | None] = mapped_column(String(100))

    members: Mapped[list[AnalysisSnapshotMember]] = relationship(
        back_populates="analysis_snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    findings: Mapped[list[AnalysisFinding]] = relationship(
        back_populates="analysis_snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AnalysisSnapshotMember(UUIDPrimaryKeyMixin, Base):
    """One row per device registered at analysis time, included or not.

    Recording exclusions as data makes the completeness disclosure queryable
    rather than recomputed, and preserves what was considered.
    """

    __tablename__ = "analysis_snapshot_members"
    __table_args__ = (
        UniqueConstraint(
            "analysis_snapshot_id", "device_id", name="uq_analysis_member_device"
        ),
    )

    analysis_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    config_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("config_snapshots.id", ondelete="RESTRICT")
    )
    batfish_hostname: Mapped[str | None] = mapped_column(String(255))
    exclusion_reason: Mapped[ExclusionReason | None] = mapped_column(
        enum_type(ExclusionReason, "exclusion_reason")
    )

    analysis_snapshot: Mapped[AnalysisSnapshot] = relationship(back_populates="members")


class AnalysisFinding(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "analysis_findings"
    __table_args__ = (
        Index("ix_analysis_findings_snapshot_category", "analysis_snapshot_id", "category"),
    )

    analysis_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[FindingCategory] = mapped_column(
        enum_type(FindingCategory, "finding_category"), nullable=False
    )
    severity: Mapped[EventSeverity] = mapped_column(
        enum_type(EventSeverity, "event_severity"),
        nullable=False,
        default=EventSeverity.WARNING,
    )
    device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    structure_type: Mapped[str | None] = mapped_column(String(100))
    structure_name: Mapped[str | None] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    line_number: Mapped[int | None] = mapped_column(Integer)

    analysis_snapshot: Mapped[AnalysisSnapshot] = relationship(back_populates="findings")
```

Export `AnalysisFinding`, `AnalysisSnapshot`, `AnalysisSnapshotMember`, `AnalysisStatus`, `ExclusionReason`, `FindingCategory` from `backend/app/models/__init__.py`, keeping both the import list and `__all__` alphabetically sorted as they already are.

- [ ] **Step 6: Run the contract test to confirm it passes**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_analysis_contracts.py -q --basetemp=<scratch>`
Expected: PASS.

- [ ] **Step 7: Write the migration**

Create `backend/migrations/versions/20260808_0008_analysis_snapshots.py`:

```python
"""Add read-only configuration analysis tables.

Revision ID: 20260808_0008
Revises: 20260808_0007
Create Date: 2026-08-08

Adds analysis_snapshots, analysis_snapshot_members and analysis_findings. No
existing table is altered, so this migration is additive on every dialect.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0008"
down_revision: str | None = "20260808_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = ("pending", "parsing", "ready", "failed", "expired")
_EXCLUSION = ("no_snapshot", "unsupported_vendor")
_CATEGORY = (
    "parse_warning",
    "undefined_reference",
    "unused_structure",
    "topology_drift",
)
_SEVERITY = ("info", "warning", "error")


def _enum(name: str, values: Sequence[str]) -> sa.Enum:
    # create_constraint=False matches app/models/entities.py, so `alembic check`
    # reports no drift. Allowed values are enforced by explicit CHECK
    # constraints below, under canonical ck_<table>_<column> names.
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False)


def upgrade() -> None:
    op.create_table(
        "analysis_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", _enum("analysis_status", _STATUS), nullable=False),
        sa.Column("device_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observed_link_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("oldest_config_at", sa.DateTime(timezone=True)),
        sa.Column("newest_config_at", sa.DateTime(timezone=True)),
        sa.Column("parse_warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "findings_truncated", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("failure_code", sa.String(length=100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ({})".format(", ".join(f"'{v}'" for v in _STATUS)),
            name="ck_analysis_snapshots_status",
        ),
    )
    op.create_table(
        "analysis_snapshot_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("config_snapshot_id", sa.Uuid()),
        sa.Column("batfish_hostname", sa.String(length=255)),
        sa.Column("exclusion_reason", _enum("exclusion_reason", _EXCLUSION)),
        sa.ForeignKeyConstraint(
            ["analysis_snapshot_id"], ["analysis_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["config_snapshot_id"], ["config_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_snapshot_id", "device_id", name="uq_analysis_member_device"
        ),
        sa.CheckConstraint(
            "exclusion_reason IS NULL OR exclusion_reason IN ({})".format(
                ", ".join(f"'{v}'" for v in _EXCLUSION)
            ),
            name="ck_analysis_snapshot_members_exclusion_reason",
        ),
    )
    op.create_index(
        "ix_analysis_snapshot_members_analysis_snapshot_id",
        "analysis_snapshot_members",
        ["analysis_snapshot_id"],
    )
    op.create_index(
        "ix_analysis_snapshot_members_device_id",
        "analysis_snapshot_members",
        ["device_id"],
    )
    op.create_table(
        "analysis_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("category", _enum("finding_category", _CATEGORY), nullable=False),
        sa.Column("severity", _enum("event_severity", _SEVERITY), nullable=False),
        sa.Column("device_id", sa.Uuid()),
        sa.Column("structure_type", sa.String(length=100)),
        sa.Column("structure_name", sa.String(length=255)),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("line_number", sa.Integer()),
        sa.ForeignKeyConstraint(
            ["analysis_snapshot_id"], ["analysis_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "category IN ({})".format(", ".join(f"'{v}'" for v in _CATEGORY)),
            name="ck_analysis_findings_category",
        ),
    )
    op.create_index(
        "ix_analysis_findings_analysis_snapshot_id",
        "analysis_findings",
        ["analysis_snapshot_id"],
    )
    op.create_index("ix_analysis_findings_device_id", "analysis_findings", ["device_id"])
    op.create_index(
        "ix_analysis_findings_snapshot_category",
        "analysis_findings",
        ["analysis_snapshot_id", "category"],
    )


def downgrade() -> None:
    op.drop_table("analysis_findings")
    op.drop_table("analysis_snapshot_members")
    op.drop_table("analysis_snapshots")
```

- [ ] **Step 8: Extend the migration tests**

In `backend/tests/integration/test_migrations.py`, add the three table names to the `issubset(tables)` assertion inside `test_migration_chain_upgrade_and_downgrade`:

```python
            "analysis_snapshots",
            "analysis_snapshot_members",
            "analysis_findings",
```

The existing `test_migrations_match_the_orm_models` already asserts `alembic check` is clean and will catch any drift between these models and the migration. No new test is needed for that.

- [ ] **Step 9: Run the full migration and contract suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py tests/unit/test_analysis_contracts.py -q --basetemp=<scratch>`
Expected: PASS, including the `alembic check` drift test.

If drift is reported, the model and migration disagree. Match the migration to the model rather than the reverse; the ORM is the source of truth here.

- [ ] **Step 10: Run lint and types**

Run: `cd backend && .venv/Scripts/python.exe -m ruff check --no-cache . && .venv/Scripts/pyright.exe`
Expected: all checks pass, 0 errors.

- [ ] **Step 11: Commit**

```bash
git add backend/app/core/config.py backend/app/core/errors.py \
  backend/app/models/entities.py backend/app/models/__init__.py \
  backend/migrations/versions/20260808_0008_analysis_snapshots.py \
  backend/tests/unit/test_analysis_contracts.py \
  backend/tests/integration/test_migrations.py
git commit -m "feat: add analysis settings, errors, and schema

Adds the ANALYSIS_ENABLED kill switch (default off), six typed analysis
errors, and the three analysis tables. Additive migration; no existing
table is altered."
```

---

## Task 2: Snapshot builder

Pure logic with no Batfish dependency, so it is the most testable part of the feature and worth isolating. It decides what goes into an analysis and what is excluded, which is what the completeness disclosure reports.

**Files:**
- Create: `backend/app/analysis/__init__.py`
- Create: `backend/app/analysis/types.py`
- Create: `backend/app/analysis/snapshot_builder.py`
- Test: `backend/tests/unit/test_analysis_snapshot_builder.py`

**Interfaces:**
- Consumes: `AnalysisStatus`, `ExclusionReason` from Task 1; `SnapshotService.get_sanitized_content(snapshot_id) -> tuple[ConfigSnapshot, str]`; `Vendor`, `Device`, `Neighbor` models.
- Produces:
  - `DeviceConfig(device_id: UUID, config_snapshot_id: UUID, batfish_hostname: str, content: str, captured_at: datetime)`
  - `ExcludedDevice(device_id: UUID, reason: ExclusionReason)`
  - `Layer1Edge(node1_hostname: str, node1_interface: str, node2_hostname: str, node2_interface: str)`
  - `AnalysisInput(configs: tuple[DeviceConfig, ...], excluded: tuple[ExcludedDevice, ...], layer1_edges: tuple[Layer1Edge, ...])`
  - `batfish_hostname(config: str, fallback: str) -> str`
  - `build_analysis_input(devices, latest_snapshot_for, sanitized_content_for, neighbors, *, max_devices) -> AnalysisInput`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_analysis_snapshot_builder.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.analysis.snapshot_builder import batfish_hostname, build_analysis_input
from app.analysis.types import Layer1Edge
from app.models import ExclusionReason, Vendor


class FakeDevice:
    def __init__(self, name: str, vendor: Vendor) -> None:
        self.id = uuid4()
        self.name = name
        self.vendor = vendor


def _snapshot(device_id: UUID, captured_at: datetime) -> object:
    return type(
        "Snap", (), {"id": uuid4(), "device_id": device_id, "created_at": captured_at}
    )()


def test_hostname_comes_from_the_configuration_not_the_record() -> None:
    """Batfish keys nodes on the configured hostname, lowercased."""
    config = "!\nversion 15.2\nhostname Core-SW-01\n!\n"
    assert batfish_hostname(config, fallback="whatever") == "core-sw-01"


def test_hostname_falls_back_when_the_configuration_has_none() -> None:
    assert batfish_hostname("!\nversion 15.2\n!\n", fallback="Edge Router") == "edge-router"


def test_unsupported_vendors_are_recorded_as_exclusions_not_dropped() -> None:
    cisco = FakeDevice("sw1", Vendor.CISCO_IOSXE)
    forti = FakeDevice("fw1", Vendor.FORTINET_FORTIOS)
    generic = FakeDevice("box", Vendor.GENERIC)
    now = datetime.now(UTC)

    result = build_analysis_input(
        devices=[cisco, forti, generic],
        latest_snapshot_for={cisco.id: _snapshot(cisco.id, now)},
        sanitized_content_for={},
        neighbors=[],
        max_devices=200,
    )

    assert len(result.configs) == 1
    reasons = {item.device_id: item.reason for item in result.excluded}
    assert reasons[forti.id] is ExclusionReason.UNSUPPORTED_VENDOR
    assert reasons[generic.id] is ExclusionReason.UNSUPPORTED_VENDOR


def test_devices_without_a_snapshot_are_recorded_as_exclusions() -> None:
    with_snap = FakeDevice("sw1", Vendor.CISCO_IOSXE)
    without = FakeDevice("sw2", Vendor.CISCO_IOSXE)
    now = datetime.now(UTC)

    result = build_analysis_input(
        devices=[with_snap, without],
        latest_snapshot_for={with_snap.id: _snapshot(with_snap.id, now)},
        sanitized_content_for={},
        neighbors=[],
        max_devices=200,
    )

    assert [item.reason for item in result.excluded] == [ExclusionReason.NO_SNAPSHOT]
    assert [item.device_id for item in result.excluded] == [without.id]


def test_layer1_edges_only_include_links_where_both_ends_are_analysed() -> None:
    """A neighbour whose remote device is excluded cannot form an edge."""
    sw1 = FakeDevice("sw1", Vendor.CISCO_IOSXE)
    sw2 = FakeDevice("sw2", Vendor.CISCO_IOSXE)
    now = datetime.now(UTC)
    neighbours = [
        type(
            "N",
            (),
            {
                "device_id": sw1.id,
                "local_interface": "GigabitEthernet0/1",
                "remote_device_name": "SW2",
                "remote_interface": "GigabitEthernet0/2",
            },
        )(),
        type(
            "N",
            (),
            {
                "device_id": sw1.id,
                "local_interface": "GigabitEthernet0/3",
                "remote_device_name": "unknown-box",
                "remote_interface": "eth0",
            },
        )(),
    ]

    result = build_analysis_input(
        devices=[sw1, sw2],
        latest_snapshot_for={
            sw1.id: _snapshot(sw1.id, now),
            sw2.id: _snapshot(sw2.id, now),
        },
        sanitized_content_for={sw1.id: "hostname sw1\n", sw2.id: "hostname sw2\n"},
        neighbors=neighbours,
        max_devices=200,
    )

    assert result.layer1_edges == (
        Layer1Edge("sw1", "GigabitEthernet0/1", "sw2", "GigabitEthernet0/2"),
    )


def test_config_age_range_is_reported() -> None:
    sw1 = FakeDevice("sw1", Vendor.CISCO_IOSXE)
    sw2 = FakeDevice("sw2", Vendor.CISCO_IOSXE)
    old = datetime(2026, 8, 1, tzinfo=UTC)
    new = datetime(2026, 8, 7, tzinfo=UTC)

    result = build_analysis_input(
        devices=[sw1, sw2],
        latest_snapshot_for={sw1.id: _snapshot(sw1.id, old), sw2.id: _snapshot(sw2.id, new)},
        sanitized_content_for={sw1.id: "hostname sw1\n", sw2.id: "hostname sw2\n"},
        neighbors=[],
        max_devices=200,
    )

    assert result.oldest_config_at == old
    assert result.newest_config_at == new


def test_device_count_over_the_bound_is_rejected() -> None:
    devices = [FakeDevice(f"sw{index}", Vendor.CISCO_IOSXE) for index in range(3)]
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="exceeds the analysis device bound"):
        build_analysis_input(
            devices=devices,
            latest_snapshot_for={item.id: _snapshot(item.id, now) for item in devices},
            sanitized_content_for={item.id: f"hostname {item.name}\n" for item in devices},
            neighbors=[],
            max_devices=2,
        )
```

- [ ] **Step 2: Run to confirm it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_analysis_snapshot_builder.py -q --basetemp=<scratch>`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis'`.

- [ ] **Step 3: Create the shared types**

Create `backend/app/analysis/__init__.py`:

```python
from app.analysis.types import (
    AnalysisInput,
    DeviceConfig,
    ExcludedDevice,
    Layer1Edge,
)

__all__ = ["AnalysisInput", "DeviceConfig", "ExcludedDevice", "Layer1Edge"]
```

Create `backend/app/analysis/types.py`:

```python
"""Types shared across the analysis package.

No Batfish or pandas type appears here or crosses this package's boundary. The
rest of the application depends on these dataclasses only, so the analysis
backend can be replaced without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.models import ExclusionReason


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    device_id: UUID
    config_snapshot_id: UUID
    batfish_hostname: str
    content: str
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class ExcludedDevice:
    device_id: UUID
    reason: ExclusionReason


@dataclass(frozen=True, slots=True)
class Layer1Edge:
    node1_hostname: str
    node1_interface: str
    node2_hostname: str
    node2_interface: str


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    configs: tuple[DeviceConfig, ...]
    excluded: tuple[ExcludedDevice, ...]
    layer1_edges: tuple[Layer1Edge, ...]
    oldest_config_at: datetime | None
    newest_config_at: datetime | None
```

- [ ] **Step 4: Implement the builder**

Create `backend/app/analysis/snapshot_builder.py`:

```python
"""Assemble the configuration set and layer-1 topology for one analysis.

Deliberately free of Batfish and of database session handling: callers supply
already-resolved devices, snapshots and sanitized content. That keeps the
classification rules — which decide what the completeness disclosure reports —
testable without a container or a database.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.analysis.types import AnalysisInput, DeviceConfig, ExcludedDevice, Layer1Edge
from app.models import ExclusionReason, Vendor

# Batfish can parse Cisco IOS/IOS-XE. FortiOS support is limited and the generic
# driver reads nothing, so both are excluded rather than parsed badly.
SUPPORTED_VENDORS = frozenset({Vendor.CISCO_IOSXE})

_HOSTNAME = re.compile(r"^\s*hostname\s+(\S+)\s*$", re.MULTILINE)
_UNSAFE_HOSTNAME_CHARS = re.compile(r"[^a-z0-9._-]+")


class _HasIdVendor(Protocol):
    id: UUID
    name: str
    vendor: Vendor


class _HasCreatedAt(Protocol):
    id: UUID
    created_at: datetime


class _HasNeighbor(Protocol):
    device_id: UUID
    local_interface: str
    remote_device_name: str
    remote_interface: str


def batfish_hostname(config: str, *, fallback: str) -> str:
    """Return the node name Batfish will use for this configuration.

    Batfish keys nodes on the configured hostname, lowercased. Reading it from
    the configuration rather than from collected facts avoids a mismatch when
    the two disagree: the configuration is what Batfish actually parses.
    """
    match = _HOSTNAME.search(config)
    raw = match.group(1) if match is not None else fallback
    return _UNSAFE_HOSTNAME_CHARS.sub("-", raw.strip().lower()).strip("-")


def build_analysis_input(
    *,
    devices: Iterable[_HasIdVendor],
    latest_snapshot_for: Mapping[UUID, _HasCreatedAt],
    sanitized_content_for: Mapping[UUID, str],
    neighbors: Sequence[_HasNeighbor],
    max_devices: int,
) -> AnalysisInput:
    device_list = list(devices)
    included = [
        device
        for device in device_list
        if device.vendor in SUPPORTED_VENDORS and device.id in latest_snapshot_for
    ]
    if len(included) > max_devices:
        raise ValueError(
            f"{len(included)} devices exceeds the analysis device bound of {max_devices}"
        )

    configs: list[DeviceConfig] = []
    excluded: list[ExcludedDevice] = []
    for device in device_list:
        if device.vendor not in SUPPORTED_VENDORS:
            excluded.append(ExcludedDevice(device.id, ExclusionReason.UNSUPPORTED_VENDOR))
            continue
        snapshot = latest_snapshot_for.get(device.id)
        if snapshot is None:
            excluded.append(ExcludedDevice(device.id, ExclusionReason.NO_SNAPSHOT))
            continue
        content = sanitized_content_for.get(device.id, "")
        configs.append(
            DeviceConfig(
                device_id=device.id,
                config_snapshot_id=snapshot.id,
                batfish_hostname=batfish_hostname(content, fallback=device.name),
                content=content,
                captured_at=snapshot.created_at,
            )
        )

    captured = [item.captured_at for item in configs]
    return AnalysisInput(
        configs=tuple(configs),
        excluded=tuple(excluded),
        layer1_edges=_layer1_edges(configs, neighbors),
        oldest_config_at=min(captured) if captured else None,
        newest_config_at=max(captured) if captured else None,
    )


def _layer1_edges(
    configs: Sequence[DeviceConfig], neighbors: Sequence[_HasNeighbor]
) -> tuple[Layer1Edge, ...]:
    """Derive layer-1 edges from observed neighbours.

    Batfish accepts a layer-1 topology as snapshot input. Supplying observed
    CDP/LLDP links is what makes reachability meaningful on a switched campus,
    where most access ports carry no layer-3 address for Batfish to infer
    adjacency from.

    Only links whose both ends are in the analysed set can become edges: an edge
    naming a node Batfish has never seen would be silently ignored at best.
    """
    hostname_by_device = {item.device_id: item.batfish_hostname for item in configs}
    analysed_hostnames = set(hostname_by_device.values())

    edges: set[Layer1Edge] = set()
    for neighbor in neighbors:
        local = hostname_by_device.get(neighbor.device_id)
        if local is None:
            continue
        remote = batfish_hostname("", fallback=neighbor.remote_device_name)
        # CDP often reports a fully qualified name; Batfish uses the short one.
        remote = remote.split(".", 1)[0]
        if remote not in analysed_hostnames:
            continue
        edges.add(
            Layer1Edge(
                node1_hostname=local,
                node1_interface=neighbor.local_interface,
                node2_hostname=remote,
                node2_interface=neighbor.remote_interface,
            )
        )
    return tuple(sorted(edges, key=lambda edge: (edge.node1_hostname, edge.node1_interface)))
```

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_analysis_snapshot_builder.py -q --basetemp=<scratch>`
Expected: PASS, 6 tests.

- [ ] **Step 6: Run lint and types**

Run: `cd backend && .venv/Scripts/python.exe -m ruff check --no-cache . && .venv/Scripts/pyright.exe`
Expected: all checks pass, 0 errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/analysis backend/tests/unit/test_analysis_snapshot_builder.py
git commit -m "feat: assemble analysis configuration set and layer-1 topology

Classifies every registered device as included or excluded, reads the
Batfish node name from the configuration rather than collected facts, and
derives layer-1 edges from observed CDP/LLDP links whose both ends are in
the analysed set."
```

---

## Task 3: Batfish client, optional dependency, and Compose profile

Isolates every Batfish detail behind one module and one protocol, and makes the container real so the opt-in validation in Task 9 has something to run against.

**Files:**
- Create: `backend/app/analysis/client.py`
- Create: `deploy/compose.analysis.yml`
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/container.py`
- Modify: `backend/tests/fakes.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/unit/test_analysis_client.py`

**Interfaces:**
- Consumes: `AnalysisInput`, `Layer1Edge` from Task 2; settings and errors from Task 1.
- Produces:
  - `RawFinding(category: FindingCategory, hostname: str | None, structure_type: str | None, structure_name: str | None, detail: str, line_number: int | None)`
  - `InterfaceProperty(hostname: str, interface: str, switchport_mode: str | None, access_vlan: int | None)`
  - `TraceHop(hostname: str, action: str, detail: str)`
  - `TraceResult(disposition: str, hops: tuple[TraceHop, ...])`
  - `FilterVerdict(permitted: bool, matched_line_index: int | None, matched_line: str | None)`
  - `AnalysisBackend` Protocol with: `init_snapshot(name, configs: Mapping[str, str], layer1_edges: Sequence[Layer1Edge]) -> None`, `snapshot_exists(name) -> bool`, `parse_findings(name) -> tuple[RawFinding, ...]`, `interface_properties(name) -> tuple[InterfaceProperty, ...]`, `traceroute(name, start_hostname, destination_ip) -> TraceResult`, `test_filter(name, hostname, filter_name, destination_ip, protocol, destination_port) -> FilterVerdict`
  - `PyBatfishBackend` implementing it
  - `build_backend(settings) -> AnalysisBackend` raising `AnalysisUnavailableError` when `pybatfish` is absent
  - `container.analysis_client` returning `AnalysisBackend`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_analysis_client.py`:

```python
from __future__ import annotations

import sys

import pytest

from app.analysis.client import build_backend
from app.core.config import Settings
from app.core.errors import AnalysisUnavailableError


def test_missing_pybatfish_fails_closed_with_a_typed_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Analysis becomes unavailable; the application must still run."""
    monkeypatch.setitem(sys.modules, "pybatfish", None)
    monkeypatch.setitem(sys.modules, "pybatfish.client.session", None)

    with pytest.raises(AnalysisUnavailableError) as raised:
        build_backend(settings)

    assert raised.value.code == "analysis_unavailable"
    assert "pybatfish" not in raised.value.message.lower()
```

Add to `backend/tests/unit/test_analysis_snapshot_builder.py` nothing; this file covers the client only.

- [ ] **Step 2: Run to confirm it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_analysis_client.py -q --basetemp=<scratch>`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.client'`.

- [ ] **Step 3: Implement the client**

Create `backend/app/analysis/client.py`:

```python
"""The only module that knows Batfish exists.

`pybatfish` pulls in pandas and numpy, so it is an optional dependency and is
imported at call time rather than at module import. The same pattern is used for
Scrapli in app/drivers/transport.py. When it is absent the application still
starts and analysis endpoints return a typed error.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.analysis.types import Layer1Edge
from app.core.config import Settings
from app.core.errors import (
    AnalysisBackendUnavailableError,
    AnalysisSnapshotExpiredError,
    AnalysisUnavailableError,
)
from app.models import FindingCategory


@dataclass(frozen=True, slots=True)
class RawFinding:
    category: FindingCategory
    hostname: str | None
    structure_type: str | None
    structure_name: str | None
    detail: str
    line_number: int | None


@dataclass(frozen=True, slots=True)
class InterfaceProperty:
    hostname: str
    interface: str
    switchport_mode: str | None
    access_vlan: int | None


@dataclass(frozen=True, slots=True)
class TraceHop:
    hostname: str
    action: str
    detail: str


@dataclass(frozen=True, slots=True)
class TraceResult:
    disposition: str
    hops: tuple[TraceHop, ...]


@dataclass(frozen=True, slots=True)
class FilterVerdict:
    permitted: bool
    matched_line_index: int | None
    matched_line: str | None


class AnalysisBackend(Protocol):
    def init_snapshot(
        self,
        name: str,
        configs: Mapping[str, str],
        layer1_edges: Sequence[Layer1Edge],
    ) -> None: ...

    def snapshot_exists(self, name: str) -> bool: ...

    def parse_findings(self, name: str) -> tuple[RawFinding, ...]: ...

    def interface_properties(self, name: str) -> tuple[InterfaceProperty, ...]: ...

    def traceroute(
        self, name: str, start_hostname: str, destination_ip: str
    ) -> TraceResult: ...

    def test_filter(
        self,
        name: str,
        hostname: str,
        filter_name: str,
        destination_ip: str,
        protocol: str,
        destination_port: int | None,
    ) -> FilterVerdict: ...


def build_backend(settings: Settings) -> AnalysisBackend:
    try:
        from pybatfish.client.session import Session
    except Exception as exc:  # noqa: BLE001
        # Never surface the import error: it names paths and module versions.
        raise AnalysisUnavailableError() from None
    del exc  # pyright: ignore[reportUnusedExpression]
    return PyBatfishBackend(Session, settings)


class PyBatfishBackend:
    def __init__(self, session_factory: Any, settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._session: Any | None = None

    def _connect(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            session = self._session_factory(host=self._settings.batfish_host)
            session.port_v2 = self._settings.batfish_port
        except Exception:  # noqa: BLE001
            raise AnalysisBackendUnavailableError() from None
        self._session = session
        return session

    def init_snapshot(
        self,
        name: str,
        configs: Mapping[str, str],
        layer1_edges: Sequence[Layer1Edge],
    ) -> None:
        import json
        import tempfile
        from pathlib import Path

        session = self._connect()
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            config_dir = root / "configs"
            config_dir.mkdir()
            for hostname, content in configs.items():
                (config_dir / f"{hostname}.cfg").write_text(content, encoding="utf-8")
            if layer1_edges:
                batfish_dir = root / "batfish"
                batfish_dir.mkdir()
                (batfish_dir / "layer1_topology.json").write_text(
                    json.dumps(
                        [
                            {
                                "node1": {
                                    "hostname": edge.node1_hostname,
                                    "interfaceName": edge.node1_interface,
                                },
                                "node2": {
                                    "hostname": edge.node2_hostname,
                                    "interfaceName": edge.node2_interface,
                                },
                            }
                            for edge in layer1_edges
                        ]
                    ),
                    encoding="utf-8",
                )
            try:
                session.set_network(name)
                session.init_snapshot(str(root), name=name, overwrite=True)
            except Exception:  # noqa: BLE001
                raise AnalysisBackendUnavailableError() from None

    def snapshot_exists(self, name: str) -> bool:
        session = self._connect()
        try:
            session.set_network(name)
            return name in set(session.list_snapshots())
        except Exception:  # noqa: BLE001
            return False

    def _ask(self, name: str, question: Any) -> list[dict[str, Any]]:
        session = self._connect()
        try:
            session.set_network(name)
            session.set_snapshot(name)
            frame = question.answer().frame()
        except Exception:  # noqa: BLE001
            if not self.snapshot_exists(name):
                raise AnalysisSnapshotExpiredError() from None
            raise AnalysisBackendUnavailableError() from None
        return [
            {str(key): value for key, value in record.items()}
            for record in frame.to_dict(orient="records")
        ]

    def parse_findings(self, name: str) -> tuple[RawFinding, ...]:
        session = self._connect()
        questions = session.q
        findings: list[RawFinding] = []
        for row in self._ask(name, questions.initIssues()):
            findings.append(
                RawFinding(
                    category=FindingCategory.PARSE_WARNING,
                    hostname=_text(row.get("Nodes")),
                    structure_type=None,
                    structure_name=None,
                    detail=f"{_text(row.get('Type'))}: {_text(row.get('Details'))}",
                    line_number=_number(row.get("Line_Text")),
                )
            )
        for row in self._ask(name, questions.undefinedReferences()):
            findings.append(
                RawFinding(
                    category=FindingCategory.UNDEFINED_REFERENCE,
                    hostname=_text(row.get("File_Name")),
                    structure_type=_text(row.get("Struct_Type")),
                    structure_name=_text(row.get("Ref_Name")),
                    detail=f"{_text(row.get('Context'))} references an undefined structure",
                    line_number=_number(row.get("Lines")),
                )
            )
        for row in self._ask(name, questions.unusedStructures()):
            findings.append(
                RawFinding(
                    category=FindingCategory.UNUSED_STRUCTURE,
                    hostname=_text(row.get("File_Name")),
                    structure_type=_text(row.get("Struct_Type")),
                    structure_name=_text(row.get("Struct_Name")),
                    detail="Structure is defined but never used",
                    line_number=_number(row.get("Lines")),
                )
            )
        return tuple(findings)

    def interface_properties(self, name: str) -> tuple[InterfaceProperty, ...]:
        session = self._connect()
        rows = self._ask(
            name,
            session.q.interfaceProperties(
                properties="Switchport_Mode|Access_VLAN"
            ),
        )
        results: list[InterfaceProperty] = []
        for row in rows:
            interface = _text(row.get("Interface")) or ""
            hostname, _, port = interface.partition("[")
            results.append(
                InterfaceProperty(
                    hostname=hostname.strip(),
                    interface=port.rstrip("]").strip() or interface,
                    switchport_mode=_text(row.get("Switchport_Mode")),
                    access_vlan=_number(row.get("Access_VLAN")),
                )
            )
        return tuple(results)

    def traceroute(
        self, name: str, start_hostname: str, destination_ip: str
    ) -> TraceResult:
        session = self._connect()
        rows = self._ask(
            name,
            session.q.traceroute(
                startLocation=start_hostname,
                headers={"dstIps": destination_ip},
            ),
        )
        if not rows:
            return TraceResult(disposition="NO_RESULT", hops=())
        traces = rows[0].get("Traces")
        first = _first_trace(traces)
        return TraceResult(
            disposition=_text(getattr(first, "disposition", None)) or "UNKNOWN",
            hops=tuple(
                TraceHop(
                    hostname=_text(getattr(hop, "node", None)) or "",
                    action=_text(getattr(hop, "action", None)) or "",
                    detail=str(hop),
                )
                for hop in getattr(first, "hops", []) or []
            ),
        )

    def test_filter(
        self,
        name: str,
        hostname: str,
        filter_name: str,
        destination_ip: str,
        protocol: str,
        destination_port: int | None,
    ) -> FilterVerdict:
        session = self._connect()
        headers: dict[str, Any] = {"dstIps": destination_ip, "ipProtocols": protocol}
        if destination_port is not None:
            headers["dstPorts"] = str(destination_port)
        rows = self._ask(
            name,
            session.q.testFilters(nodes=hostname, filters=filter_name, headers=headers),
        )
        if not rows:
            return FilterVerdict(permitted=False, matched_line_index=None, matched_line=None)
        row = rows[0]
        return FilterVerdict(
            permitted=_text(row.get("Action")) == "PERMIT",
            matched_line_index=_number(row.get("Line_Index")),
            matched_line=_text(row.get("Line_Content")),
        )


def _first_trace(traces: Any) -> Any:
    if isinstance(traces, (list, tuple)) and traces:
        return traces[0]
    return traces


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)) and value:
        return _number(value[0])
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
```

Note on `build_backend`: the `del exc` line exists only to satisfy the linter about the unused name. If Ruff still objects, change the `except` clause to `except Exception:` without binding a name and drop the `del`. That is the preferred form; keep the error opaque either way.

- [ ] **Step 4: Add the optional dependency**

In `backend/pyproject.toml`, after the `[dependency-groups]` block:

```toml
[project.optional-dependencies]
# Read-only configuration analysis. Kept out of the default install because
# pybatfish pulls in pandas and numpy, which would sit in the always-on image
# even when ANALYSIS_ENABLED is false.
analysis = [
  "pybatfish==2024.7.15.1341",
]
```

Pin whatever version resolves at implementation time and record it here; do not leave the version floating.

- [ ] **Step 5: Add the Compose profile**

Create `deploy/compose.analysis.yml`:

```yaml
# Optional read-only configuration analysis. Enable with:
#   docker compose --env-file .env -f deploy/compose.yml \
#     -f deploy/compose.analysis.yml --profile analysis up --detach --wait
#
# Batfish receives sanitized configuration text and returns findings. It holds
# no credentials and has no reason to reach a device, so the `analysis` network
# is internal-only. This is deliberately stricter than the `application`
# network, which must retain outbound routing for the worker.
services:
  batfish:
    profiles: ["analysis"]
    image: batfish/allinone:2024.07.15.1341
    init: true
    restart: unless-stopped
    networks:
      - analysis
    expose:
      - "9996"
      - "9997"
    volumes:
      - batfish_data:/data
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:9996/ >/dev/null || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 60s

  api:
    environment:
      ANALYSIS_ENABLED: "${ANALYSIS_ENABLED:-false}"
      BATFISH_HOST: batfish
      BATFISH_PORT: "9996"
    networks:
      - edge
      - application
      - analysis

  worker:
    environment:
      ANALYSIS_ENABLED: "${ANALYSIS_ENABLED:-false}"
      BATFISH_HOST: batfish
      BATFISH_PORT: "9996"
    networks:
      - application
      - analysis

networks:
  analysis:
    driver: bridge
    internal: true

volumes:
  batfish_data:
```

Verify the image tag exists before committing; if `batfish/allinone` publishes a different tag, use the newest published tag and record it.

- [ ] **Step 6: Wire the container**

In `backend/app/container.py`, add to `ApplicationContainer`:

```python
    @cached_property
    def analysis_client(self) -> AnalysisBackend:
        return build_backend(self.settings)
```

Import `build_backend` and `AnalysisBackend` from `app.analysis.client`. Add an `analysis_client: AnalysisBackend | None = None` keyword to `__init__`, store it as `self._analysis_client`, and have the property return the injected instance when present. Follow the existing pattern used for `drivers` and `queue`.

- [ ] **Step 7: Add the fake backend**

Append to `backend/tests/fakes.py`:

```python
class FakeBatfishClient:
    """In-memory analysis backend.

    Records exactly what was handed to Batfish so tests can assert that no raw
    secret left the database.
    """

    def __init__(self) -> None:
        self.snapshots: dict[str, dict[str, str]] = {}
        self.layer1_edges: dict[str, tuple[object, ...]] = {}
        self.parse_findings_result: tuple[object, ...] = ()
        self.interface_properties_result: tuple[object, ...] = ()
        self.trace_result: object | None = None
        self.filter_verdict: object | None = None
        self.init_error: Exception | None = None

    def init_snapshot(self, name, configs, layer1_edges) -> None:  # noqa: ANN001
        if self.init_error is not None:
            raise self.init_error
        self.snapshots[name] = dict(configs)
        self.layer1_edges[name] = tuple(layer1_edges)

    def snapshot_exists(self, name: str) -> bool:
        return name in self.snapshots

    def parse_findings(self, name: str):  # noqa: ANN201
        self._require(name)
        return self.parse_findings_result

    def interface_properties(self, name: str):  # noqa: ANN201
        self._require(name)
        return self.interface_properties_result

    def traceroute(self, name, start_hostname, destination_ip):  # noqa: ANN001, ANN201
        self._require(name)
        return self.trace_result

    def test_filter(  # noqa: ANN201
        self, name, hostname, filter_name, destination_ip, protocol, destination_port
    ):  # noqa: ANN001
        self._require(name)
        return self.filter_verdict

    def forget(self, name: str) -> None:
        """Simulate the container losing a parsed snapshot on restart."""
        self.snapshots.pop(name, None)

    def _require(self, name: str) -> None:
        from app.core.errors import AnalysisSnapshotExpiredError

        if name not in self.snapshots:
            raise AnalysisSnapshotExpiredError()
```

- [ ] **Step 8: Wire the fake into the test container**

In `backend/tests/conftest.py`, add a fixture and pass it through:

```python
@pytest.fixture
def fake_batfish() -> FakeBatfishClient:
    return FakeBatfishClient()
```

Add `fake_batfish: FakeBatfishClient` to the `container` fixture's parameters, pass `analysis_client=fake_batfish,  # type: ignore[arg-type]` to `ApplicationContainer(...)`, and import `FakeBatfishClient` from `tests.fakes`. Set `analysis_enabled=True` in the `settings` fixture so integration tests exercise the feature; Task 5 adds an explicit test that the disabled path fails closed by overriding it.

- [ ] **Step 9: Run the client test and the whole suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q --basetemp=<scratch>`
Expected: PASS. The new client test passes and no existing test regresses.

- [ ] **Step 10: Validate both Compose configurations**

Run:
```bash
docker compose --env-file .env.example -f deploy/compose.yml -f deploy/compose.analysis.yml config --quiet
docker compose --env-file .env.example -f deploy/compose.yml -f deploy/compose.dev.yml config --quiet
```
Expected: both exit 0.

Then confirm the profile is genuinely off by default:
```bash
docker compose --env-file .env.example -f deploy/compose.yml -f deploy/compose.analysis.yml config --services
```
Expected: `batfish` is absent from the output, because it is profile-gated.

- [ ] **Step 11: Run lint and types, then commit**

Run: `cd backend && .venv/Scripts/python.exe -m ruff check --no-cache . && .venv/Scripts/pyright.exe`

```bash
git add backend/app/analysis/client.py backend/app/container.py backend/pyproject.toml \
  backend/tests/fakes.py backend/tests/conftest.py \
  backend/tests/unit/test_analysis_client.py deploy/compose.analysis.yml
git commit -m "feat: add Batfish backend behind an optional profile

pybatfish is an optional dependency imported at call time, so the default
image is unchanged and a missing install yields a typed analysis_unavailable
error rather than a failed start. The batfish service is profile-gated on an
internal-only network with no secrets and no route to devices."
```

---

## Task 4: Findings mapping and sanitization

Turns raw backend rows into persisted findings. Separated because sanitization and capping are security properties that deserve their own gate, and they are pure functions.

**Files:**
- Create: `backend/app/analysis/findings.py`
- Create: `backend/app/repositories/analysis.py`
- Test: `backend/tests/unit/test_analysis_findings.py`

**Interfaces:**
- Consumes: `RawFinding` from Task 3; `AnalysisFinding`, `FindingCategory`, `EventSeverity` from Task 1.
- Produces:
  - `to_findings(raw: Sequence[RawFinding], *, hostname_to_device: Mapping[str, UUID], max_findings: int) -> tuple[list[PreparedFinding], bool]` where the bool is `truncated`
  - `PreparedFinding(category, severity, device_id, structure_type, structure_name, detail, line_number)`
  - `AnalysisRepository` with `create(...)`, `get(...)`, `set_status(...)`, `add_members(...)`, `add_findings(...)`, `list_findings(...)`, `prune(keep: int)`
  - `DETAIL_MAX_LENGTH = 2000`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_analysis_findings.py`:

```python
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
```

- [ ] **Step 2: Run to confirm it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_analysis_findings.py -q --basetemp=<scratch>`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.findings'`.

- [ ] **Step 3: Implement the mapping**

Create `backend/app/analysis/findings.py`:

```python
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
```

- [ ] **Step 4: Run to confirm the mapping tests pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_analysis_findings.py -q --basetemp=<scratch>`
Expected: PASS, 7 tests.

If the sanitization test fails, check what `sanitize_text` actually redacts by reading `backend/app/core/logging.py`, and change the fixture string to a pattern it recognises. Do not weaken the assertion to make it pass; the point is that a community string cannot reach storage.

- [ ] **Step 5: Implement the repository**

Create `backend/app/repositories/analysis.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.findings import PreparedFinding
from app.core.errors import NotFoundError
from app.models import (
    AnalysisFinding,
    AnalysisSnapshot,
    AnalysisSnapshotMember,
    AnalysisStatus,
    ExclusionReason,
    FindingCategory,
)


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self) -> AnalysisSnapshot:
        snapshot = AnalysisSnapshot(status=AnalysisStatus.PENDING)
        self._session.add(snapshot)
        self._session.flush()
        return snapshot

    def get(self, snapshot_id: UUID, *, for_update: bool = False) -> AnalysisSnapshot:
        statement = select(AnalysisSnapshot).where(AnalysisSnapshot.id == snapshot_id)
        if for_update:
            statement = statement.with_for_update()
        snapshot = self._session.scalars(statement).one_or_none()
        if snapshot is None:
            raise NotFoundError("The requested analysis snapshot was not found")
        return snapshot

    def latest(self) -> AnalysisSnapshot | None:
        return self._session.scalars(
            select(AnalysisSnapshot).order_by(AnalysisSnapshot.created_at.desc()).limit(1)
        ).one_or_none()

    def list(self, *, limit: int = 20) -> list[AnalysisSnapshot]:
        return list(
            self._session.scalars(
                select(AnalysisSnapshot)
                .order_by(AnalysisSnapshot.created_at.desc())
                .limit(limit)
            )
        )

    def set_status(
        self,
        snapshot: AnalysisSnapshot,
        status: AnalysisStatus,
        *,
        failure_code: str | None = None,
    ) -> None:
        snapshot.status = status
        snapshot.failure_code = failure_code

    def record_scope(
        self,
        snapshot: AnalysisSnapshot,
        *,
        device_count: int,
        observed_link_count: int,
        oldest_config_at: datetime | None,
        newest_config_at: datetime | None,
    ) -> None:
        snapshot.device_count = device_count
        snapshot.observed_link_count = observed_link_count
        snapshot.oldest_config_at = oldest_config_at
        snapshot.newest_config_at = newest_config_at

    def add_member(
        self,
        snapshot: AnalysisSnapshot,
        *,
        device_id: UUID,
        config_snapshot_id: UUID | None,
        batfish_hostname: str | None,
        exclusion_reason: ExclusionReason | None,
    ) -> None:
        self._session.add(
            AnalysisSnapshotMember(
                analysis_snapshot_id=snapshot.id,
                device_id=device_id,
                config_snapshot_id=config_snapshot_id,
                batfish_hostname=batfish_hostname,
                exclusion_reason=exclusion_reason,
            )
        )

    def list_members(self, snapshot_id: UUID) -> list[AnalysisSnapshotMember]:
        return list(
            self._session.scalars(
                select(AnalysisSnapshotMember).where(
                    AnalysisSnapshotMember.analysis_snapshot_id == snapshot_id
                )
            )
        )

    def add_findings(
        self, snapshot: AnalysisSnapshot, findings: Sequence[PreparedFinding]
    ) -> None:
        for finding in findings:
            self._session.add(
                AnalysisFinding(
                    analysis_snapshot_id=snapshot.id,
                    category=finding.category,
                    severity=finding.severity,
                    device_id=finding.device_id,
                    structure_type=finding.structure_type,
                    structure_name=finding.structure_name,
                    detail=finding.detail,
                    line_number=finding.line_number,
                )
            )
        snapshot.parse_warning_count = sum(
            1 for item in findings if item.category is FindingCategory.PARSE_WARNING
        )

    def list_findings(
        self,
        snapshot_id: UUID,
        *,
        category: FindingCategory | None = None,
        device_id: UUID | None = None,
    ) -> list[AnalysisFinding]:
        statement = select(AnalysisFinding).where(
            AnalysisFinding.analysis_snapshot_id == snapshot_id
        )
        if category is not None:
            statement = statement.where(AnalysisFinding.category == category)
        if device_id is not None:
            statement = statement.where(AnalysisFinding.device_id == device_id)
        return list(self._session.scalars(statement))

    def prune(self, *, keep: int) -> int:
        """Delete all but the newest `keep` snapshots; findings cascade."""
        keep_ids = list(
            self._session.scalars(
                select(AnalysisSnapshot.id)
                .order_by(AnalysisSnapshot.created_at.desc())
                .limit(keep)
            )
        )
        if not keep_ids:
            return 0
        result = self._session.execute(
            delete(AnalysisSnapshot).where(AnalysisSnapshot.id.notin_(keep_ids))
        )
        return int(result.rowcount or 0)
```

- [ ] **Step 6: Run the full suite, lint, and types**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q --basetemp=<scratch> && .venv/Scripts/python.exe -m ruff check --no-cache . && .venv/Scripts/pyright.exe`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/analysis/findings.py backend/app/repositories/analysis.py \
  backend/tests/unit/test_analysis_findings.py
git commit -m "feat: map and sanitize analysis findings

Findings detail is sanitized and length-capped before storage because Batfish
quotes offending configuration lines. Adds the analysis repository, including
retention pruning."
```

---

## Task 5: Initialisation service, job, and API

The first task that produces something an operator can use. Ends with a snapshot that exists, reports its own completeness, and fails closed when disabled.

**Files:**
- Create: `backend/app/analysis/service.py`
- Create: `backend/app/schemas/analysis.py`
- Create: `backend/app/api/analysis.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/jobs/tasks.py`
- Test: `backend/tests/integration/test_analysis_vertical_slice.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces:
  - `AnalysisService(session, *, settings, backend, snapshots)` with `initialise_new() -> dict[str, object]` (the job entry point; creates the row then parses), `initialise(analysis_snapshot_id: UUID) -> dict[str, object]` (re-parse an existing row), and `completeness(snapshot: AnalysisSnapshot) -> CompletenessView`
  - Schemas: `AnalysisSnapshotView`, `CompletenessView`, `ExclusionView`, `FindingView`
  - Endpoints: `POST /api/analysis-snapshots` (202 + `JobView`), `GET /api/analysis-snapshots`, `GET /api/analysis-snapshots/{id}`, `GET /api/analysis-snapshots/{id}/findings`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_analysis_vertical_slice.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from app.analysis.client import RawFinding
from app.container import ApplicationContainer
from app.jobs import tasks
from app.models import FindingCategory
from tests.fakes import FakeBatfishClient


def _register_cisco(client: TestClient, profile_id: str, address: str) -> str:
    connection = {
        "management_address": address,
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": profile_id,
        "ssh_compatibility": "modern",
    }
    candidate = client.post("/api/ssh-host-key-candidates", json=connection)
    assert candidate.status_code == 201, candidate.text
    created = client.post(
        "/api/devices",
        json={
            "name": f"sw-{address}",
            **connection,
            "host_key_candidate_id": candidate.json()["id"],
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _capture(client: TestClient, device_id: str, container, monkeypatch) -> None:
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    queued = client.post(f"/api/devices/{device_id}/config-snapshots")
    assert queued.status_code == 202, queued.text
    tasks.execute_job(queued.json()["id"])


def test_analysis_reports_completeness_including_excluded_devices(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    profile_id = str(credential_profile["id"])
    analysed = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _register_cisco(authenticated_client, profile_id, "192.0.2.11")  # no snapshot
    _capture(authenticated_client, analysed, container, monkeypatch)

    queued = authenticated_client.post("/api/analysis-snapshots")
    assert queued.status_code == 202, queued.text
    tasks.execute_job(queued.json()["id"])

    listed = authenticated_client.get("/api/analysis-snapshots")
    assert listed.status_code == 200, listed.text
    snapshot = listed.json()[0]

    assert snapshot["status"] == "ready"
    assert snapshot["completeness"]["analysed_device_count"] == 1
    assert snapshot["completeness"]["registered_device_count"] == 2
    exclusions = {item["reason"]: item["count"] for item in snapshot["completeness"]["exclusions"]}
    assert exclusions["no_snapshot"] == 1


def test_only_sanitized_configuration_reaches_the_backend(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    """The running-config fixture contains secrets; none may reach Batfish."""
    profile_id = str(credential_profile["id"])
    device_id = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _capture(authenticated_client, device_id, container, monkeypatch)

    queued = authenticated_client.post("/api/analysis-snapshots")
    tasks.execute_job(queued.json()["id"])

    sent = "\n".join(
        content for configs in fake_batfish.snapshots.values() for content in configs.values()
    )
    assert sent, "no configuration was handed to the backend"
    assert "SANITIZED_ENABLE_HASH" not in sent
    assert "SANITIZED_USER_HASH" not in sent
    assert "SANITIZED_COMMUNITY" not in sent
    assert "[REDACTED]" in sent


def test_findings_are_persisted_and_listable(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    fake_batfish.parse_findings_result = (
        RawFinding(
            category=FindingCategory.UNDEFINED_REFERENCE,
            hostname="edge-rtr-01",
            structure_type="ipv4 access-list",
            structure_name="MISSING_ACL",
            detail="interface GigabitEthernet1 references an undefined structure",
            line_number=42,
        ),
    )
    profile_id = str(credential_profile["id"])
    device_id = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _capture(authenticated_client, device_id, container, monkeypatch)

    queued = authenticated_client.post("/api/analysis-snapshots")
    tasks.execute_job(queued.json()["id"])
    snapshot_id = authenticated_client.get("/api/analysis-snapshots").json()[0]["id"]

    findings = authenticated_client.get(
        f"/api/analysis-snapshots/{snapshot_id}/findings",
        params={"category": "undefined_reference"},
    )

    assert findings.status_code == 200, findings.text
    assert findings.json()[0]["structure_name"] == "MISSING_ACL"
    assert findings.json()[0]["device_id"] == device_id


def test_analysis_without_any_snapshot_is_rejected(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.10")

    queued = authenticated_client.post("/api/analysis-snapshots")
    assert queued.status_code == 202
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    job_id = queued.json()["id"]
    tasks.execute_job(job_id)

    state = authenticated_client.get(f"/api/jobs/{job_id}").json()
    assert state["state"] == "failed"
    assert state["error_code"] == "analysis_no_configs"


def test_every_endpoint_fails_closed_when_analysis_is_disabled(
    authenticated_client: TestClient,
    container: ApplicationContainer,
) -> None:
    container.settings.analysis_enabled = False

    for method, path in (
        ("post", "/api/analysis-snapshots"),
        ("get", "/api/analysis-snapshots"),
    ):
        response = getattr(authenticated_client, method)(path)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["error"]["code"] == "analysis_disabled_by_policy"


def test_only_one_analysis_may_be_active(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    """Parsing is CPU- and memory-intensive and Batfish is a single instance."""
    profile_id = str(credential_profile["id"])
    device_id = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _capture(authenticated_client, device_id, container, monkeypatch)

    first = authenticated_client.post("/api/analysis-snapshots")
    assert first.status_code == 202, first.text
    second = authenticated_client.post("/api/analysis-snapshots")

    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "conflict"
    assert "analysis" in second.json()["error"]["message"].lower()


def test_retention_keeps_only_the_configured_number_of_snapshots(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.analysis_retained_snapshots = 2
    profile_id = str(credential_profile["id"])
    device_id = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _capture(authenticated_client, device_id, container, monkeypatch)

    for _ in range(3):
        queued = authenticated_client.post("/api/analysis-snapshots")
        tasks.execute_job(queued.json()["id"])

    assert len(authenticated_client.get("/api/analysis-snapshots").json()) == 2
```

- [ ] **Step 2: Run to confirm it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_analysis_vertical_slice.py -q --basetemp=<scratch>`
Expected: FAIL with 404 on `/api/analysis-snapshots`.

- [ ] **Step 3: Write the schemas**

Create `backend/app/schemas/analysis.py`:

```python
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
```

- [ ] **Step 4: Write the service**

Create `backend/app/analysis/service.py`:

```python
"""Orchestrates analysis initialisation and completeness reporting.

The API and the worker both go through this class; neither touches the backend
client or the repository directly.
"""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from sqlalchemy.orm import Session

from app.analysis.client import AnalysisBackend
from app.analysis.findings import to_findings
from app.analysis.snapshot_builder import build_analysis_input
from app.core.config import Settings
from app.core.errors import AnalysisNoConfigsError, AppError
from app.models import AnalysisSnapshot, AnalysisStatus, ExclusionReason
from app.repositories.analysis import AnalysisRepository
from app.repositories.devices import DeviceRepository
from app.repositories.events import EventRepository
from app.schemas.analysis import CompletenessView, ExclusionView
from app.services.snapshots import SnapshotService


class AnalysisService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        backend: AnalysisBackend,
        snapshots: SnapshotService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._backend = backend
        self._snapshots = snapshots
        self._analysis = AnalysisRepository(session)
        self._devices = DeviceRepository(session)
        self._events = EventRepository(session)

    def initialise_new(self) -> dict[str, object]:
        """Create the snapshot row and parse it.

        The row is created here rather than in the API handler so a request
        rejected by the one-at-a-time guard cannot leave an orphan `pending`
        row behind.
        """
        snapshot = self._analysis.create()
        self._session.commit()
        return self.initialise(snapshot.id)

    def initialise(self, analysis_snapshot_id: UUID) -> dict[str, object]:
        snapshot = self._analysis.get(analysis_snapshot_id, for_update=True)
        self._analysis.set_status(snapshot, AnalysisStatus.PARSING)
        self._session.commit()

        try:
            result = self._initialise(snapshot)
        except AppError as error:
            self._analysis.set_status(
                snapshot, AnalysisStatus.FAILED, failure_code=error.code
            )
            self._session.commit()
            raise
        self._session.commit()
        return result

    def _initialise(self, snapshot: AnalysisSnapshot) -> dict[str, object]:
        devices = self._devices.list()
        latest: dict[UUID, object] = {}
        content: dict[UUID, str] = {}
        for device in devices:
            stored = self._snapshots.list(device_id=device.id, limit=1)
            if not stored:
                continue
            latest[device.id] = stored[0]
            _record, sanitized = self._snapshots.get_sanitized_content(stored[0].id)
            content[device.id] = sanitized

        neighbors = [
            neighbor for device in devices for neighbor in self._devices.list_neighbors(device.id)
        ]
        analysis_input = build_analysis_input(
            devices=devices,
            latest_snapshot_for=latest,  # type: ignore[arg-type]
            sanitized_content_for=content,
            neighbors=neighbors,  # type: ignore[arg-type]
            max_devices=self._settings.analysis_max_devices,
        )
        if not analysis_input.configs:
            raise AnalysisNoConfigsError()

        for config in analysis_input.configs:
            self._analysis.add_member(
                snapshot,
                device_id=config.device_id,
                config_snapshot_id=config.config_snapshot_id,
                batfish_hostname=config.batfish_hostname,
                exclusion_reason=None,
            )
        for excluded in analysis_input.excluded:
            self._analysis.add_member(
                snapshot,
                device_id=excluded.device_id,
                config_snapshot_id=None,
                batfish_hostname=None,
                exclusion_reason=excluded.reason,
            )
        self._analysis.record_scope(
            snapshot,
            device_count=len(analysis_input.configs),
            observed_link_count=len(analysis_input.layer1_edges),
            oldest_config_at=analysis_input.oldest_config_at,
            newest_config_at=analysis_input.newest_config_at,
        )

        self._backend.init_snapshot(
            str(snapshot.id),
            {item.batfish_hostname: item.content for item in analysis_input.configs},
            analysis_input.layer1_edges,
        )
        raw = self._backend.parse_findings(str(snapshot.id))
        hostname_to_device = {
            item.batfish_hostname: item.device_id for item in analysis_input.configs
        }
        prepared, truncated = to_findings(
            raw,
            hostname_to_device=hostname_to_device,
            max_findings=self._settings.analysis_max_findings,
        )
        self._analysis.add_findings(snapshot, prepared)
        snapshot.findings_truncated = truncated
        self._analysis.set_status(snapshot, AnalysisStatus.READY)

        self._events.record(
            event_type="analysis.completed",
            message="Read-only configuration analysis completed",
            details={
                "analysis_snapshot_id": str(snapshot.id),
                "analysed_device_count": len(analysis_input.configs),
                "excluded_device_count": len(analysis_input.excluded),
                "observed_link_count": len(analysis_input.layer1_edges),
                "finding_count": len(prepared),
                "evidence": "INFERRED",
            },
        )
        self._analysis.prune(keep=self._settings.analysis_retained_snapshots)
        return {
            "analysis_snapshot_id": str(snapshot.id),
            "analysed_device_count": len(analysis_input.configs),
            "finding_count": len(prepared),
        }

    def completeness(self, snapshot: AnalysisSnapshot) -> CompletenessView:
        members = self._analysis.list_members(snapshot.id)
        counts: Counter[ExclusionReason] = Counter(
            member.exclusion_reason
            for member in members
            if member.exclusion_reason is not None
        )
        return CompletenessView(
            registered_device_count=len(members),
            analysed_device_count=snapshot.device_count,
            observed_link_count=snapshot.observed_link_count,
            exclusions=[
                ExclusionView(reason=reason, count=count) for reason, count in sorted(counts.items())
            ],
            oldest_config_at=snapshot.oldest_config_at,
            newest_config_at=snapshot.newest_config_at,
        )
```

If `DeviceRepository` has no `list_neighbors`, read `backend/app/repositories/devices.py` and use whatever accessor the neighbours endpoint already uses; do not add a second query path.

- [ ] **Step 5: Write the API**

Create `backend/app/api/analysis.py`:

```python
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from app.analysis.service import AnalysisService
from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.core.errors import AnalysisDisabledByPolicyError
from app.models import FindingCategory, JobType
from app.repositories.analysis import AnalysisRepository
from app.schemas.analysis import AnalysisSnapshotView, FindingView
from app.schemas.jobs import JobView
from app.services.devices import DeviceService
from app.services.jobs import JobService
from app.services.snapshots import SnapshotService

router = APIRouter(prefix="/analysis-snapshots", tags=["analysis"])


def _require_enabled(container: ContainerDependency) -> None:
    if not container.settings.analysis_enabled:
        raise AnalysisDisabledByPolicyError()


def _service(session: SessionDependency, container: ContainerDependency) -> AnalysisService:
    devices = DeviceService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
    )
    return AnalysisService(
        session,
        settings=container.settings,
        backend=container.analysis_client,
        snapshots=SnapshotService(
            session,
            store=container.snapshot_store,
            devices=devices,
            drivers=container.drivers,
        ),
    )


@router.post("", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
def start_analysis(
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    _require_enabled(container)
    # The snapshot row is created by the job, not here: a request rejected by
    # the one-at-a-time guard must not leave an orphan pending row.
    return JobService(session, container.queue).enqueue(
        job_type=JobType.ANALYZE_NETWORK,
    )


@router.get("", response_model=list[AnalysisSnapshotView])
def list_analysis_snapshots(
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    _require_enabled(container)
    service = _service(session, container)
    return [
        AnalysisSnapshotView(
            id=snapshot.id,
            status=snapshot.status,
            parse_warning_count=snapshot.parse_warning_count,
            findings_truncated=snapshot.findings_truncated,
            failure_code=snapshot.failure_code,
            completeness=service.completeness(snapshot),
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
        )
        for snapshot in AnalysisRepository(session).list()
    ]


@router.get("/{analysis_snapshot_id}", response_model=AnalysisSnapshotView)
def get_analysis_snapshot(
    analysis_snapshot_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    _require_enabled(container)
    service = _service(session, container)
    snapshot = AnalysisRepository(session).get(analysis_snapshot_id)
    return AnalysisSnapshotView(
        id=snapshot.id,
        status=snapshot.status,
        parse_warning_count=snapshot.parse_warning_count,
        findings_truncated=snapshot.findings_truncated,
        failure_code=snapshot.failure_code,
        completeness=service.completeness(snapshot),
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )


@router.get("/{analysis_snapshot_id}/findings", response_model=list[FindingView])
def list_findings(
    analysis_snapshot_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
    category: FindingCategory | None = Query(default=None),
    device_id: UUID | None = Query(default=None),
):
    _require_enabled(container)
    return AnalysisRepository(session).list_findings(
        analysis_snapshot_id, category=category, device_id=device_id
    )
```

Register it in `backend/app/api/router.py` by importing `analysis` and adding `api_router.include_router(analysis.router)` after the `devices` router.

- [ ] **Step 5b: Enforce one active analysis at a time**

Spec §8.3 requires this. The codebase already has the mechanism: `JobService.enqueue` rejects a second concurrent discovery using `JobRepository.has_active`. Extend that condition rather than adding a second, parallel check in the analysis service.

In `backend/app/services/jobs.py`, replace the discovery guard:

```python
        if job_type == JobType.DISCOVER_SSH and self._jobs.has_active(job_type):
            raise ConflictError("A discovery job is already active")
```

with a table-driven form so the rule is stated once:

```python
        # Job types that must not run concurrently with themselves. Discovery
        # touches many devices; analysis parses the whole configuration set and
        # Batfish is a single instance.
        if job_type in _EXCLUSIVE_JOB_TYPES and self._jobs.has_active(job_type):
            raise ConflictError(_EXCLUSIVE_JOB_TYPES[job_type])
```

and add near the top of the module:

```python
_EXCLUSIVE_JOB_TYPES = {
    JobType.DISCOVER_SSH: "A discovery job is already active",
    JobType.ANALYZE_NETWORK: "An analysis job is already active",
}
```

The existing discovery test must keep passing unchanged; its message is preserved verbatim. Run the discovery suite explicitly to confirm:

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_discovery_vertical_slice.py -q --basetemp=<scratch>`
Expected: PASS with no change to that file.

Note that `create_snapshot` creates the `analysis_snapshots` row before `enqueue` is called, so a rejected second request leaves an orphan `pending` row. Avoid that by enqueuing first: in `start_analysis`, call `JobService(...).enqueue(...)` with a placeholder-free flow by creating the row only after the job is accepted. The simplest correct ordering is to move the row creation into the job itself — have `start_analysis` enqueue with empty input, and have `AnalysisService.initialise` create the snapshot row when it runs. Adjust the job dispatch in Step 6 to call `analysis.initialise_new()` which creates the row and then runs the same `_initialise` body, and drop `analysis_snapshot_id` from the job input.

- [ ] **Step 6: Dispatch the job**

In `backend/app/jobs/tasks.py`, add a branch inside `execute_job` before the final `else`:

```python
            elif job.type == JobType.ANALYZE_NETWORK and job.device_id is None:
                analysis = AnalysisService(
                    session,
                    settings=container.settings,
                    backend=container.analysis_client,
                    snapshots=SnapshotService(
                        session,
                        store=container.snapshot_store,
                        devices=devices,
                        drivers=container.drivers,
                    ),
                )
                result = analysis.initialise_new()
```

Import `AnalysisService` from `app.analysis.service` at the top of the file.

The job carries no input: `initialise_new` creates the snapshot row itself. Later tasks locate the snapshot through `GET /api/analysis-snapshots`, whose first element is the newest, or through the `analysis_snapshot_id` in the job result.

- [ ] **Step 7: Run the integration tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_analysis_vertical_slice.py -q --basetemp=<scratch>`
Expected: PASS, 6 tests.

The sanitization test depends on the running-config fixture containing the markers it asserts on. Confirm them by reading `backend/tests/fixtures/cisco_iosxe/running_config.txt`, and use markers that file actually contains.

- [ ] **Step 8: Run the whole suite, lint, and types**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q --basetemp=<scratch> && .venv/Scripts/python.exe -m ruff check --no-cache . && .venv/Scripts/pyright.exe`
Expected: all pass, no regression.

- [ ] **Step 9: Commit**

```bash
git add backend/app/analysis/service.py backend/app/schemas/analysis.py \
  backend/app/api/analysis.py backend/app/api/router.py backend/app/jobs/tasks.py \
  backend/tests/integration/test_analysis_vertical_slice.py
git commit -m "feat: initialise analysis snapshots from stored configuration

Adds the analysis job, endpoints, and completeness reporting. Exclusions are
persisted per registered device so the disclosure is queryable rather than
recomputed. Every endpoint fails closed when ANALYSIS_ENABLED is false, and
retention keeps only the configured number of snapshots."
```

---

## Task 6: Topology drift findings

Answers "does my configuration match my cabling", scoped per spec §3.1 to differences that are genuinely detectable.

**Files:**
- Create: `backend/app/analysis/drift.py`
- Modify: `backend/app/analysis/service.py`
- Test: `backend/tests/unit/test_analysis_drift.py`

**Interfaces:**
- Consumes: `InterfaceProperty` from Task 3; `Layer1Edge` from Task 2; `RawFinding` from Task 3.
- Produces: `topology_drift_findings(edges: Sequence[Layer1Edge], properties: Sequence[InterfaceProperty]) -> tuple[RawFinding, ...]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_analysis_drift.py`:

```python
from __future__ import annotations

from app.analysis.client import InterfaceProperty
from app.analysis.drift import topology_drift_findings
from app.analysis.types import Layer1Edge
from app.models import FindingCategory


def _edge() -> Layer1Edge:
    return Layer1Edge("sw1", "GigabitEthernet0/1", "sw2", "GigabitEthernet0/2")


def test_interface_seen_by_cdp_but_absent_from_configuration_is_reported() -> None:
    properties = [InterfaceProperty("sw2", "GigabitEthernet0/2", "ACCESS", 10)]

    findings = topology_drift_findings([_edge()], properties)

    assert len(findings) == 1
    assert findings[0].category is FindingCategory.TOPOLOGY_DRIFT
    assert "GigabitEthernet0/1" in findings[0].detail
    assert findings[0].hostname == "sw1"


def test_matching_access_vlans_produce_no_finding() -> None:
    properties = [
        InterfaceProperty("sw1", "GigabitEthernet0/1", "ACCESS", 10),
        InterfaceProperty("sw2", "GigabitEthernet0/2", "ACCESS", 10),
    ]

    assert topology_drift_findings([_edge()], properties) == ()


def test_access_vlan_mismatch_across_an_observed_link_is_reported() -> None:
    properties = [
        InterfaceProperty("sw1", "GigabitEthernet0/1", "ACCESS", 10),
        InterfaceProperty("sw2", "GigabitEthernet0/2", "ACCESS", 20),
    ]

    findings = topology_drift_findings([_edge()], properties)

    assert len(findings) == 1
    assert "access VLAN" in findings[0].detail
    assert "10" in findings[0].detail and "20" in findings[0].detail


def test_switchport_mode_mismatch_across_an_observed_link_is_reported() -> None:
    properties = [
        InterfaceProperty("sw1", "GigabitEthernet0/1", "ACCESS", 10),
        InterfaceProperty("sw2", "GigabitEthernet0/2", "TRUNK", None),
    ]

    findings = topology_drift_findings([_edge()], properties)

    assert len(findings) == 1
    assert "switchport mode" in findings[0].detail


def test_no_edges_produce_no_findings() -> None:
    assert topology_drift_findings([], []) == ()
```

- [ ] **Step 2: Run to confirm it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_analysis_drift.py -q --basetemp=<scratch>`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.drift'`.

- [ ] **Step 3: Implement drift detection**

Create `backend/app/analysis/drift.py`:

```python
"""Compare observed cabling against parsed configuration.

Deliberately narrow. CDP/LLDP report layer-2 neighbour and interface pairs,
while Batfish layer-3 edges report routed adjacencies; on a campus most observed
links are not layer-3 edges, so comparing those two would report large numbers
of false differences. Only two checks are made, both of which are answerable
from data the application actually holds:

1. An interface named in an observed link does not exist in the configuration.
2. The two ends of an observed link disagree on switchport mode or access VLAN.

Both describe the same real fault: cabled one way, configured another.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.analysis.client import InterfaceProperty, RawFinding
from app.analysis.types import Layer1Edge
from app.models import FindingCategory


def topology_drift_findings(
    edges: Sequence[Layer1Edge], properties: Sequence[InterfaceProperty]
) -> tuple[RawFinding, ...]:
    by_key = {
        (item.hostname.lower(), item.interface.lower()): item for item in properties
    }
    findings: list[RawFinding] = []

    for edge in edges:
        near_key = (edge.node1_hostname.lower(), edge.node1_interface.lower())
        far_key = (edge.node2_hostname.lower(), edge.node2_interface.lower())
        near = by_key.get(near_key)
        far = by_key.get(far_key)

        for hostname, interface, found in (
            (edge.node1_hostname, edge.node1_interface, near),
            (edge.node2_hostname, edge.node2_interface, far),
        ):
            if found is None:
                findings.append(
                    RawFinding(
                        category=FindingCategory.TOPOLOGY_DRIFT,
                        hostname=hostname,
                        structure_type="interface",
                        structure_name=interface,
                        detail=(
                            f"{interface} is reported by a neighbour discovery record"
                            " but does not appear in the parsed configuration"
                        ),
                        line_number=None,
                    )
                )
        if near is None or far is None:
            continue

        if _mode(near) != _mode(far):
            findings.append(
                RawFinding(
                    category=FindingCategory.TOPOLOGY_DRIFT,
                    hostname=edge.node1_hostname,
                    structure_type="interface",
                    structure_name=edge.node1_interface,
                    detail=(
                        "Observed link ends disagree on switchport mode:"
                        f" {edge.node1_hostname} {edge.node1_interface} is {_mode(near)}"
                        f" and {edge.node2_hostname} {edge.node2_interface} is {_mode(far)}"
                    ),
                    line_number=None,
                )
            )
        elif (
            _mode(near) == "ACCESS"
            and near.access_vlan is not None
            and far.access_vlan is not None
            and near.access_vlan != far.access_vlan
        ):
            findings.append(
                RawFinding(
                    category=FindingCategory.TOPOLOGY_DRIFT,
                    hostname=edge.node1_hostname,
                    structure_type="interface",
                    structure_name=edge.node1_interface,
                    detail=(
                        "Observed link ends disagree on access VLAN:"
                        f" {edge.node1_hostname} {edge.node1_interface} uses"
                        f" {near.access_vlan} and {edge.node2_hostname}"
                        f" {edge.node2_interface} uses {far.access_vlan}"
                    ),
                    line_number=None,
                )
            )
    return tuple(findings)


def _mode(item: InterfaceProperty) -> str:
    return (item.switchport_mode or "UNKNOWN").upper()
```

- [ ] **Step 4: Run to confirm the drift tests pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_analysis_drift.py -q --basetemp=<scratch>`
Expected: PASS, 5 tests.

- [ ] **Step 5: Include drift findings in initialisation**

In `backend/app/analysis/service.py`, inside `_initialise`, replace the single `raw = self._backend.parse_findings(...)` line with:

```python
        raw = self._backend.parse_findings(str(snapshot.id))
        raw += topology_drift_findings(
            analysis_input.layer1_edges,
            self._backend.interface_properties(str(snapshot.id)),
        )
```

Import `topology_drift_findings` from `app.analysis.drift`.

- [ ] **Step 6: Add an integration test for drift**

Append to `backend/tests/integration/test_analysis_vertical_slice.py`:

```python
def test_topology_drift_is_persisted_as_a_finding(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    """The configured interface is missing, which the drift check must catch."""
    from app.analysis.client import InterfaceProperty

    fake_batfish.interface_properties_result = (
        InterfaceProperty("edge-rtr-01", "GigabitEthernet1", "ACCESS", 10),
    )
    profile_id = str(credential_profile["id"])
    device_id = _register_cisco(authenticated_client, profile_id, "192.0.2.10")
    _capture(authenticated_client, device_id, container, monkeypatch)
    # Refresh populates neighbours from the CDP/LLDP fixtures.
    refresh = authenticated_client.post(f"/api/devices/{device_id}/refresh")
    tasks.execute_job(refresh.json()["id"])

    queued = authenticated_client.post("/api/analysis-snapshots")
    tasks.execute_job(queued.json()["id"])
    snapshot_id = authenticated_client.get("/api/analysis-snapshots").json()[0]["id"]

    findings = authenticated_client.get(
        f"/api/analysis-snapshots/{snapshot_id}/findings",
        params={"category": "topology_drift"},
    )

    assert findings.status_code == 200, findings.text
    assert all(item["evidence"] == "INFERRED" for item in findings.json())
```

The CDP fixture reports neighbours whose remote devices are not registered, so `layer1_edges` may be empty and this test may legitimately find zero drift findings. If so, register a second device whose configured hostname matches the fixture's `remote_device_name` so an edge can form, and assert at least one finding. Do not weaken the assertion to `>= 0`.

- [ ] **Step 7: Run the full suite, lint, and types, then commit**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q --basetemp=<scratch> && .venv/Scripts/python.exe -m ruff check --no-cache . && .venv/Scripts/pyright.exe`

```bash
git add backend/app/analysis/drift.py backend/app/analysis/service.py \
  backend/tests/unit/test_analysis_drift.py \
  backend/tests/integration/test_analysis_vertical_slice.py
git commit -m "feat: detect topology drift between cabling and configuration

Scoped to interfaces an observed link names but the configuration lacks, and
link ends that disagree on switchport mode or access VLAN. Comparing observed
layer-2 links against Batfish layer-3 edges is not a valid comparison and is
deliberately not done."
```

---

## Task 7: Interactive queries

The part that makes the feature feel like a playground: ask, see the answer, change the question.

**Files:**
- Modify: `backend/app/schemas/analysis.py`
- Modify: `backend/app/api/analysis.py`
- Modify: `backend/app/analysis/service.py`
- Test: `backend/tests/integration/test_analysis_queries.py`

**Interfaces:**
- Consumes: `TraceResult`, `TraceHop`, `FilterVerdict` from Task 3.
- Produces:
  - `PathCheckRequest(source_device_id: UUID, destination_ip: IPvAnyAddress)`
  - `FilterCheckRequest(device_id: UUID, filter_name: str, destination_ip: IPvAnyAddress, protocol: Literal["tcp","udp","icmp"], destination_port: int | None)`
  - `PathCheckView(disposition, hops: list[TraceHopView], evidence="INFERRED", completeness: CompletenessView)`
  - `FilterCheckView(permitted, matched_line_index, matched_line, evidence="INFERRED", completeness: CompletenessView)`
  - `AnalysisService.path_check(...)`, `AnalysisService.filter_check(...)`
  - Endpoints: `POST /api/analysis-snapshots/{id}/path-checks`, `POST /api/analysis-snapshots/{id}/filter-checks`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_analysis_queries.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from app.analysis.client import FilterVerdict, TraceHop, TraceResult
from app.container import ApplicationContainer
from app.jobs import tasks
from tests.fakes import FakeBatfishClient
from tests.integration.test_analysis_vertical_slice import _capture, _register_cisco


def _ready_snapshot(
    client: TestClient, profile_id: str, container: ApplicationContainer, monkeypatch
) -> tuple[str, str]:
    device_id = _register_cisco(client, profile_id, "192.0.2.10")
    _capture(client, device_id, container, monkeypatch)
    queued = client.post("/api/analysis-snapshots")
    tasks.execute_job(queued.json()["id"])
    return device_id, client.get("/api/analysis-snapshots").json()[0]["id"]


def test_path_check_returns_hops_a_disposition_and_the_disclosure(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    fake_batfish.trace_result = TraceResult(
        disposition="DENIED_IN",
        hops=(TraceHop("edge-rtr-01", "DENIED", "ACL BLOCK_GUEST line 20"),),
    )
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )

    response = authenticated_client.post(
        f"/api/analysis-snapshots/{snapshot_id}/path-checks",
        json={"source_device_id": device_id, "destination_ip": "198.51.100.10"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disposition"] == "DENIED_IN"
    assert body["hops"][0]["hostname"] == "edge-rtr-01"
    assert body["evidence"] == "INFERRED"
    assert body["completeness"]["analysed_device_count"] == 1


def test_path_check_rejects_a_non_exact_ipv4_destination(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )

    for destination in ("198.51.100.0/24", "not-an-ip", "example.test"):
        response = authenticated_client.post(
            f"/api/analysis-snapshots/{snapshot_id}/path-checks",
            json={"source_device_id": device_id, "destination_ip": destination},
        )
        assert response.status_code == 422, (destination, response.text)


def test_filter_check_reports_the_matching_line(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    fake_batfish.filter_verdict = FilterVerdict(
        permitted=False, matched_line_index=3, matched_line="deny ip any any"
    )
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )

    response = authenticated_client.post(
        f"/api/analysis-snapshots/{snapshot_id}/filter-checks",
        json={
            "device_id": device_id,
            "filter_name": "BLOCK_GUEST",
            "destination_ip": "198.51.100.10",
            "protocol": "tcp",
            "destination_port": 443,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["permitted"] is False
    assert response.json()["matched_line"] == "deny ip any any"


def test_a_lost_snapshot_is_reported_as_expired_rather_than_reparsed(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    fake_batfish: FakeBatfishClient,
    monkeypatch,
) -> None:
    """Re-parsing inside a synchronous request would hide minutes of work."""
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )
    fake_batfish.forget(snapshot_id)

    response = authenticated_client.post(
        f"/api/analysis-snapshots/{snapshot_id}/path-checks",
        json={"source_device_id": device_id, "destination_ip": "198.51.100.10"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "analysis_snapshot_expired"
    assert (
        authenticated_client.get(f"/api/analysis-snapshots/{snapshot_id}").json()["status"]
        == "expired"
    )


def test_queries_fail_closed_when_analysis_is_disabled(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    profile_id = str(credential_profile["id"])
    device_id, snapshot_id = _ready_snapshot(
        authenticated_client, profile_id, container, monkeypatch
    )
    container.settings.analysis_enabled = False

    response = authenticated_client.post(
        f"/api/analysis-snapshots/{snapshot_id}/path-checks",
        json={"source_device_id": device_id, "destination_ip": "198.51.100.10"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "analysis_disabled_by_policy"
```

- [ ] **Step 2: Run to confirm it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_analysis_queries.py -q --basetemp=<scratch>`
Expected: FAIL with 404 on the path-checks route.

- [ ] **Step 3: Add the query schemas**

Append to `backend/app/schemas/analysis.py`:

```python
from ipaddress import IPv4Address
from typing import Literal

from pydantic import Field, field_validator


class PathCheckRequest(APIModel):
    source_device_id: UUID
    destination_ip: str

    @field_validator("destination_ip")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        # Exact IPv4 only, matching the ping/traceroute diagnostic contract.
        # CIDR, hostnames and IPv6 are rejected rather than guessed at.
        try:
            return str(IPv4Address(value.strip()))
        except ValueError as exc:
            raise ValueError("destination_ip must be an exact IPv4 address") from exc


class FilterCheckRequest(PathCheckRequest):
    device_id: UUID
    filter_name: str = Field(min_length=1, max_length=255)
    protocol: Literal["tcp", "udp", "icmp"] = "tcp"
    destination_port: int | None = Field(default=None, ge=1, le=65_535)
    source_device_id: UUID | None = None  # type: ignore[assignment]


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
```

`FilterCheckRequest` inheriting from `PathCheckRequest` to reuse the validator while overriding `source_device_id` to optional is fragile. Prefer extracting the validator into a shared mixin:

```python
class _ExactIPv4Destination(APIModel):
    destination_ip: str

    @field_validator("destination_ip")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        try:
            return str(IPv4Address(value.strip()))
        except ValueError as exc:
            raise ValueError("destination_ip must be an exact IPv4 address") from exc


class PathCheckRequest(_ExactIPv4Destination):
    source_device_id: UUID


class FilterCheckRequest(_ExactIPv4Destination):
    device_id: UUID
    filter_name: str = Field(min_length=1, max_length=255)
    protocol: Literal["tcp", "udp", "icmp"] = "tcp"
    destination_port: int | None = Field(default=None, ge=1, le=65_535)
```

Use the mixin form and delete the inheritance form.

- [ ] **Step 4: Add the service methods**

Append to `AnalysisService` in `backend/app/analysis/service.py`:

```python
    def _hostname_for(self, snapshot: AnalysisSnapshot, device_id: UUID) -> str:
        for member in self._analysis.list_members(snapshot.id):
            if member.device_id == device_id and member.batfish_hostname is not None:
                return member.batfish_hostname
        raise NotFoundError("That device is not part of this analysis snapshot")

    def _mark_expired(self, snapshot: AnalysisSnapshot) -> None:
        self._analysis.set_status(snapshot, AnalysisStatus.EXPIRED)
        self._session.commit()

    def path_check(
        self, analysis_snapshot_id: UUID, *, source_device_id: UUID, destination_ip: str
    ) -> TraceResult:
        snapshot = self._analysis.get(analysis_snapshot_id)
        hostname = self._hostname_for(snapshot, source_device_id)
        try:
            result = self._backend.traceroute(
                str(snapshot.id), hostname, destination_ip
            )
        except AnalysisSnapshotExpiredError:
            self._mark_expired(snapshot)
            raise
        self._audit_query(
            snapshot,
            "path_check",
            {"source_device_id": str(source_device_id), "destination_ip": destination_ip},
        )
        return result

    def filter_check(
        self,
        analysis_snapshot_id: UUID,
        *,
        device_id: UUID,
        filter_name: str,
        destination_ip: str,
        protocol: str,
        destination_port: int | None,
    ) -> FilterVerdict:
        snapshot = self._analysis.get(analysis_snapshot_id)
        hostname = self._hostname_for(snapshot, device_id)
        try:
            verdict = self._backend.test_filter(
                str(snapshot.id),
                hostname,
                filter_name,
                destination_ip,
                protocol,
                destination_port,
            )
        except AnalysisSnapshotExpiredError:
            self._mark_expired(snapshot)
            raise
        self._audit_query(
            snapshot,
            "filter_check",
            {
                "device_id": str(device_id),
                "filter_name": filter_name,
                "destination_ip": destination_ip,
                "protocol": protocol,
            },
        )
        return verdict

    def _audit_query(
        self, snapshot: AnalysisSnapshot, query_type: str, parameters: dict[str, str]
    ) -> None:
        """Record that a query was asked, not what it returned.

        Query results are ephemeral by design; auditing the question keeps the
        trail complete without storing analysis output.
        """
        self._events.record(
            event_type="analysis.query",
            message="Read-only analysis query executed",
            details={
                "analysis_snapshot_id": str(snapshot.id),
                "query_type": query_type,
                "evidence": "INFERRED",
                **parameters,
            },
        )
        self._session.commit()
```

Import `AnalysisSnapshotExpiredError` and `NotFoundError` from `app.core.errors`, and `FilterVerdict`, `TraceResult` from `app.analysis.client`.

- [ ] **Step 5: Add the endpoints**

Append to `backend/app/api/analysis.py`:

```python
@router.post("/{analysis_snapshot_id}/path-checks", response_model=PathCheckView)
def path_check(
    analysis_snapshot_id: UUID,
    request: PathCheckRequest,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    _require_enabled(container)
    service = _service(session, container)
    result = service.path_check(
        analysis_snapshot_id,
        source_device_id=request.source_device_id,
        destination_ip=request.destination_ip,
    )
    snapshot = AnalysisRepository(session).get(analysis_snapshot_id)
    return PathCheckView(
        disposition=result.disposition,
        hops=[
            TraceHopView(hostname=hop.hostname, action=hop.action, detail=hop.detail)
            for hop in result.hops
        ],
        completeness=service.completeness(snapshot),
    )


@router.post("/{analysis_snapshot_id}/filter-checks", response_model=FilterCheckView)
def filter_check(
    analysis_snapshot_id: UUID,
    request: FilterCheckRequest,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    _require_enabled(container)
    service = _service(session, container)
    verdict = service.filter_check(
        analysis_snapshot_id,
        device_id=request.device_id,
        filter_name=request.filter_name,
        destination_ip=request.destination_ip,
        protocol=request.protocol,
        destination_port=request.destination_port,
    )
    snapshot = AnalysisRepository(session).get(analysis_snapshot_id)
    return FilterCheckView(
        permitted=verdict.permitted,
        matched_line_index=verdict.matched_line_index,
        matched_line=verdict.matched_line,
        completeness=service.completeness(snapshot),
    )
```

Extend the schema imports at the top of the file accordingly.

- [ ] **Step 6: Run the query tests, then the full suite, lint, and types**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_analysis_queries.py -q --basetemp=<scratch>`
Expected: PASS, 5 tests.

Then: `cd backend && .venv/Scripts/python.exe -m pytest -q --basetemp=<scratch> && .venv/Scripts/python.exe -m ruff check --no-cache . && .venv/Scripts/pyright.exe`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/analysis.py backend/app/api/analysis.py \
  backend/app/analysis/service.py backend/tests/integration/test_analysis_queries.py
git commit -m "feat: add interactive path and filter checks

Queries run against the already-parsed snapshot and return in about a second.
Destinations are exact IPv4 only. A snapshot the backend has lost is reported
as expired rather than re-parsed inside a synchronous request, and the question
asked is audited while the result stays ephemeral."
```

---

## Task 8: Analysis page

**Files:**
- Create: `frontend/src/features/analysis/AnalysisPage.tsx`
- Create: `frontend/src/features/analysis/CompletenessBanner.tsx`
- Create: `frontend/src/features/analysis/FindingsTab.tsx`
- Create: `frontend/src/features/analysis/PathCheckTab.tsx`
- Create: `frontend/src/features/analysis/FilterCheckTab.tsx`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/network.ts`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/analysis-page.test.tsx`

**Interfaces:**
- Consumes: the endpoints from Tasks 5 and 7.
- Produces: TypeScript types mirroring the backend views, and `api.analysisSnapshots()`, `api.startAnalysis()`, `api.analysisFindings()`, `api.pathCheck()`, `api.filterCheck()`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/analysis-page.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { api } from '../src/api/network';
import { AnalysisPage } from '../src/features/analysis/AnalysisPage';
import type { AnalysisSnapshot } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    analysisSnapshots: vi.fn(),
    startAnalysis: vi.fn(),
    analysisFindings: vi.fn(),
    pathCheck: vi.fn(),
    filterCheck: vi.fn(),
    devices: vi.fn(),
  },
}));

const snapshot: AnalysisSnapshot = {
  id: '3f1b0b2e-6a0e-4a3f-9a1e-0c2c1f9a7b11',
  status: 'ready',
  evidence: 'INFERRED',
  parse_warning_count: 0,
  findings_truncated: false,
  failure_code: null,
  completeness: {
    registered_device_count: 12,
    analysed_device_count: 7,
    observed_link_count: 9,
    exclusions: [
      { reason: 'no_snapshot', count: 3 },
      { reason: 'unsupported_vendor', count: 2 },
    ],
    oldest_config_at: '2026-08-02T00:00:00Z',
    newest_config_at: '2026-08-08T00:00:00Z',
  },
  created_at: '2026-08-08T00:00:00Z',
  updated_at: '2026-08-08T00:00:00Z',
};

const renderPage = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AnalysisPage />
    </QueryClientProvider>,
  );
};

describe('AnalysisPage', () => {
  beforeEach(() => {
    vi.mocked(api.analysisSnapshots).mockResolvedValue([snapshot]);
    vi.mocked(api.analysisFindings).mockResolvedValue([]);
    vi.mocked(api.devices).mockResolvedValue([]);
  });

  it('always discloses how complete the analysis was', async () => {
    renderPage();

    expect(await screen.findByText(/Analysed 7 of 12 registered devices/)).toBeVisible();
    expect(screen.getByText(/3 have no configuration snapshot/)).toBeVisible();
    expect(screen.getByText(/2 run a vendor that is not supported/)).toBeVisible();
    expect(screen.getByText(/9 observed links supplied as layer-1 topology/)).toBeVisible();
  });

  it('labels the result as inferred, never as verified', async () => {
    renderPage();

    expect(await screen.findByText('INFERRED')).toBeVisible();
    expect(screen.queryByText(/healthy/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/OBSERVED/)).not.toBeInTheDocument();
  });

  it('says no findings within the analysed scope rather than claiming correctness', async () => {
    renderPage();

    expect(
      await screen.findByText('No findings within the analysed scope.'),
    ).toBeVisible();
  });

  it('offers re-parse when the snapshot has expired', async () => {
    vi.mocked(api.analysisSnapshots).mockResolvedValue([
      { ...snapshot, status: 'expired' },
    ]);

    renderPage();

    const reparse = await screen.findByRole('button', { name: /Re-parse/ });
    await userEvent.click(reparse);

    await waitFor(() => expect(api.startAnalysis).toHaveBeenCalled());
  });

  it('explains what to do when no analysis exists yet', async () => {
    vi.mocked(api.analysisSnapshots).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByRole('button', { name: /Analyse network/ })).toBeVisible();
  });
});
```

- [ ] **Step 2: Run to confirm it fails**

Run: `cd frontend && npx vitest run tests/analysis-page.test.tsx`
Expected: FAIL — cannot resolve `../src/features/analysis/AnalysisPage`.

- [ ] **Step 3: Add the types**

Append to `frontend/src/types/api.ts`:

```ts
export type AnalysisStatus = 'pending' | 'parsing' | 'ready' | 'failed' | 'expired';
export type ExclusionReason = 'no_snapshot' | 'unsupported_vendor';
export type FindingCategory =
  | 'parse_warning'
  | 'undefined_reference'
  | 'unused_structure'
  | 'topology_drift';

export interface AnalysisExclusion {
  reason: ExclusionReason;
  count: number;
}

export interface AnalysisCompleteness {
  registered_device_count: number;
  analysed_device_count: number;
  observed_link_count: number;
  exclusions: AnalysisExclusion[];
  oldest_config_at: string | null;
  newest_config_at: string | null;
}

export interface AnalysisSnapshot {
  id: string;
  status: AnalysisStatus;
  evidence: 'INFERRED';
  parse_warning_count: number;
  findings_truncated: boolean;
  failure_code: string | null;
  completeness: AnalysisCompleteness;
  created_at: string;
  updated_at: string;
}

export interface AnalysisFinding {
  id: string;
  category: FindingCategory;
  severity: 'info' | 'warning' | 'error';
  device_id: string | null;
  structure_type: string | null;
  structure_name: string | null;
  detail: string;
  line_number: number | null;
  evidence: 'INFERRED';
}

export interface TraceHop {
  hostname: string;
  action: string;
  detail: string;
}

export interface PathCheckResult {
  disposition: string;
  hops: TraceHop[];
  evidence: 'INFERRED';
  completeness: AnalysisCompleteness;
}

export interface FilterCheckResult {
  permitted: boolean;
  matched_line_index: number | null;
  matched_line: string | null;
  evidence: 'INFERRED';
  completeness: AnalysisCompleteness;
}
```

- [ ] **Step 4: Add the API methods**

Add to the `api` object in `frontend/src/api/network.ts`:

```ts
  analysisSnapshots: () => apiRequest<AnalysisSnapshot[]>('/analysis-snapshots'),
  startAnalysis: () => apiRequest<Job>('/analysis-snapshots', { method: 'POST' }),
  analysisFindings: (id: string, category?: FindingCategory) => {
    const params = new URLSearchParams();
    if (category !== undefined) params.set('category', category);
    const query = params.toString();
    return apiRequest<AnalysisFinding[]>(
      `/analysis-snapshots/${encodeURIComponent(id)}/findings${query === '' ? '' : `?${query}`}`,
    );
  },
  pathCheck: (id: string, sourceDeviceId: string, destinationIp: string) =>
    apiRequest<PathCheckResult>(`/analysis-snapshots/${encodeURIComponent(id)}/path-checks`, {
      method: 'POST',
      body: json({ source_device_id: sourceDeviceId, destination_ip: destinationIp }),
    }),
  filterCheck: (
    id: string,
    input: {
      device_id: string;
      filter_name: string;
      destination_ip: string;
      protocol: 'tcp' | 'udp' | 'icmp';
      destination_port?: number;
    },
  ) =>
    apiRequest<FilterCheckResult>(`/analysis-snapshots/${encodeURIComponent(id)}/filter-checks`, {
      method: 'POST',
      body: json(input),
    }),
```

Extend the type import at the top of the file with the new type names.

- [ ] **Step 5: Build the completeness banner**

Create `frontend/src/features/analysis/CompletenessBanner.tsx`:

```tsx
import { Info } from 'lucide-react';
import type { AnalysisCompleteness } from '../../types/api';

const REASON_TEXT: Record<string, (count: number) => string> = {
  no_snapshot: (count) => `${String(count)} have no configuration snapshot`,
  unsupported_vendor: (count) => `${String(count)} run a vendor that is not supported`,
};

/**
 * Rendered with every analysis result, without exception.
 *
 * Batfish answers only from the configurations it was given. Given three of ten
 * switches it still reports "A cannot reach B" with full confidence, so the
 * scope of the answer has to travel with the answer.
 */
export function CompletenessBanner({ completeness }: { completeness: AnalysisCompleteness }) {
  const { registered_device_count, analysed_device_count, observed_link_count } = completeness;
  const oldest = completeness.oldest_config_at;

  return (
    <div className="completeness-banner" role="note">
      <Info size={15} aria-hidden />
      <div>
        <strong>
          Analysed {analysed_device_count} of {registered_device_count} registered devices
        </strong>
        <ul>
          {completeness.exclusions.map((exclusion) => (
            <li key={exclusion.reason}>
              {REASON_TEXT[exclusion.reason]?.(exclusion.count) ??
                `${String(exclusion.count)} excluded (${exclusion.reason})`}
            </li>
          ))}
          <li>{observed_link_count} observed links supplied as layer-1 topology</li>
          {oldest === null ? null : (
            <li>Oldest configuration captured {new Date(oldest).toLocaleDateString()}</li>
          )}
        </ul>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Build the page and tabs**

Create `frontend/src/features/analysis/FindingsTab.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/network';
import { AppState, QueryErrorState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';

export function FindingsTab({ snapshotId }: { snapshotId: string }) {
  const findings = useQuery({
    queryKey: ['analysis-findings', snapshotId],
    queryFn: () => api.analysisFindings(snapshotId),
  });

  if (findings.isPending) return <AppState kind="loading" title="Loading findings" />;
  if (findings.isError) {
    return <QueryErrorState error={findings.error} onRetry={() => void findings.refetch()} />;
  }
  if (findings.data.length === 0) {
    // Deliberate wording: the absence of findings is not proof of correctness.
    return <p className="analysis-empty">No findings within the analysed scope.</p>;
  }

  return (
    <ul className="analysis-findings">
      {findings.data.map((finding) => (
        <li key={finding.id}>
          <Badge tone={finding.severity === 'error' ? 'danger' : 'warning'}>
            {finding.category.replace(/_/g, ' ')}
          </Badge>
          <span className="mono">{finding.structure_name ?? '—'}</span>
          <span>{finding.detail}</span>
        </li>
      ))}
    </ul>
  );
}
```

Create `frontend/src/features/analysis/PathCheckTab.tsx`:

```tsx
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../../api/network';
import { Button } from '../../components/ui/Button';
import { ConnectionError } from '../../components/ui/ConnectionError';
import { InputField, SelectField } from '../../components/ui/FormField';

export function PathCheckTab({ snapshotId }: { snapshotId: string }) {
  const [sourceDeviceId, setSourceDeviceId] = useState('');
  const [destinationIp, setDestinationIp] = useState('');
  const devices = useQuery({ queryKey: ['devices'], queryFn: () => api.devices() });
  const check = useMutation({
    mutationFn: () => api.pathCheck(snapshotId, sourceDeviceId, destinationIp),
  });

  return (
    <div className="stack-form">
      <div className="form-grid form-grid--two">
        <SelectField
          label="Source device"
          value={sourceDeviceId}
          onChange={(event) => setSourceDeviceId(event.target.value)}
        >
          <option value="">Select a device</option>
          {(devices.data ?? []).map((device) => (
            <option key={device.id} value={device.id}>
              {device.name}
            </option>
          ))}
        </SelectField>
        <InputField
          label="Destination IPv4"
          placeholder="198.51.100.10"
          value={destinationIp}
          onChange={(event) => setDestinationIp(event.target.value)}
        />
      </div>
      <Button
        variant="primary"
        onClick={() => check.mutate()}
        busy={check.isPending}
        disabled={sourceDeviceId === '' || destinationIp === ''}
      >
        Check path
      </Button>
      {check.isError ? <ConnectionError error={check.error} fallback="The check failed." /> : null}
      {check.data === undefined ? null : (
        <div className="analysis-trace">
          <strong>{check.data.disposition}</strong>
          <ol>
            {check.data.hops.map((hop, index) => (
              <li key={`${hop.hostname}-${String(index)}`}>
                <span className="mono">{hop.hostname}</span> {hop.action} — {hop.detail}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
```

Create `frontend/src/features/analysis/FilterCheckTab.tsx` following the same shape as `PathCheckTab`, with fields for device, filter name, destination IPv4, protocol (`tcp`/`udp`/`icmp`) and optional destination port, calling `api.filterCheck`, and rendering `permitted` plus `matched_line`.

Create `frontend/src/features/analysis/AnalysisPage.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../../api/network';
import { AppState, InlineNotice, QueryErrorState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { CompletenessBanner } from './CompletenessBanner';
import { FilterCheckTab } from './FilterCheckTab';
import { FindingsTab } from './FindingsTab';
import { PathCheckTab } from './PathCheckTab';

type TabId = 'findings' | 'path' | 'filter';

export function AnalysisPage() {
  const [tab, setTab] = useState<TabId>('findings');
  const queryClient = useQueryClient();
  const snapshots = useQuery({
    queryKey: ['analysis-snapshots'],
    queryFn: () => api.analysisSnapshots(),
  });
  const start = useMutation({
    mutationFn: () => api.startAnalysis(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['analysis-snapshots'] });
    },
  });

  if (snapshots.isPending) return <AppState kind="loading" title="Loading analysis" />;
  if (snapshots.isError) {
    return <QueryErrorState error={snapshots.error} onRetry={() => void snapshots.refetch()} />;
  }

  const latest = snapshots.data[0];
  if (latest === undefined) {
    return (
      <section className="analysis-page">
        <InlineNotice tone="safe" title="Read-only analysis">
          Analysis reasons over stored configuration snapshots. It never contacts a device.
        </InlineNotice>
        <Button variant="primary" onClick={() => start.mutate()} busy={start.isPending}>
          Analyse network
        </Button>
      </section>
    );
  }

  return (
    <section className="analysis-page">
      <header className="analysis-page__header">
        <div>
          <h2>Configuration analysis</h2>
          <Badge tone="purple">{latest.evidence}</Badge>
          <Badge tone={latest.status === 'ready' ? 'success' : 'warning'}>{latest.status}</Badge>
        </div>
        <Button onClick={() => start.mutate()} busy={start.isPending}>
          {latest.status === 'expired' ? 'Re-parse' : 'Analyse again'}
        </Button>
      </header>

      <CompletenessBanner completeness={latest.completeness} />

      {latest.status === 'expired' ? (
        <InlineNotice tone="warning" title="This analysis is no longer loaded">
          The analysis service restarted and lost the parsed snapshot. Re-parse uses the same
          stored configurations and contacts no device.
        </InlineNotice>
      ) : null}
      {latest.findings_truncated ? (
        <InlineNotice tone="warning" title="Findings were truncated">
          The finding limit was reached, so this list is incomplete.
        </InlineNotice>
      ) : null}

      <div className="analysis-tabs" role="tablist" aria-label="Analysis views">
        {(
          [
            ['findings', 'Findings'],
            ['path', 'Path check'],
            ['filter', 'Filter check'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? 'is-active' : ''}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'findings' ? <FindingsTab snapshotId={latest.id} /> : null}
      {tab === 'path' ? <PathCheckTab snapshotId={latest.id} /> : null}
      {tab === 'filter' ? <FilterCheckTab snapshotId={latest.id} /> : null}
    </section>
  );
}
```

Check the actual props of `AppState`, `InlineNotice`, `QueryErrorState`, `SelectField` and `InputField` in `frontend/src/components/ui/` and match them; the calls above assume the shapes used elsewhere in the codebase.

- [ ] **Step 7: Add the navigation entry**

In `frontend/src/components/AppShell.tsx`: extend `ViewId` with `'analysis'`, lazy-import `AnalysisPage` alongside `TopologyPage`, add a nav button using the `ScanSearch` icon from `lucide-react` labelled "Configuration analysis" following the existing button markup exactly, and add the render branch inside the same `Suspense` pattern used for `TopologyPage`.

- [ ] **Step 8: Add the styles**

Append to `frontend/src/styles.css` a block for `.analysis-page`, `.analysis-page__header`, `.completeness-banner`, `.analysis-tabs`, `.analysis-findings`, `.analysis-trace` and `.analysis-empty`, reusing the existing CSS custom properties (`--surface`, `--border`, `--muted`, `--amber-soft`) so the dark-theme override added earlier applies without further work. Wide content must scroll inside its own container: give `.analysis-findings` and `.analysis-trace` `overflow-x: auto`.

- [ ] **Step 9: Run the frontend checks**

Run: `cd frontend && npx vitest run tests/analysis-page.test.tsx`
Expected: PASS, 5 tests.

Then: `cd frontend && npm run typecheck && npm run lint && npm test -- --run && npm run build`
Expected: all pass with no regression in the existing suites.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/features/analysis frontend/src/types/api.ts \
  frontend/src/api/network.ts frontend/src/components/AppShell.tsx \
  frontend/src/styles.css frontend/tests/analysis-page.test.tsx
git commit -m "feat: add the configuration analysis page

Findings, interactive path check and filter check, with the completeness
disclosure in a shared component so no surface can omit it. Results are
labelled INFERRED, and an empty result says there were no findings within the
analysed scope rather than claiming the network is correct."
```

---

## Task 9: Real-Batfish validation and documentation

The reason this work was sequenced ahead of Phase 3 was to prove Batfish parses configuration this application captured. That proof is the deliverable.

**Files:**
- Create: `backend/tests/analysis/__init__.py`
- Create: `backend/tests/analysis/test_real_batfish.py`
- Modify: `backend/pyproject.toml`
- Modify: `.env.example`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/architecture.md`
- Modify: `docs/safety-model.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no new code interface.

- [ ] **Step 1: Register the marker and the env var**

In `backend/pyproject.toml`, add to `[tool.pytest.ini_options] markers`:

```toml
  "analysis: opt-in tests that require a running Batfish container",
```

In `.env.example`, after the `TELNET_ENABLED` block:

```bash
# Read-only configuration analysis via Batfish. Requires the analysis Compose
# profile and the optional `analysis` dependency group. Off by default: it adds
# a container that needs several GB of RAM while parsing.
ANALYSIS_ENABLED=false
```

- [ ] **Step 2: Write the opt-in real-Batfish test**

Create `backend/tests/analysis/__init__.py` (empty) and `backend/tests/analysis/test_real_batfish.py`:

```python
"""Opt-in test against a real Batfish container.

Run with the analysis profile up:

    docker compose --env-file .env -f deploy/compose.yml \
      -f deploy/compose.analysis.yml --profile analysis up --detach --wait

    RUN_ANALYSIS_TESTS=1 BATFISH_HOST=127.0.0.1 \
      .venv/Scripts/python.exe -m pytest tests/analysis -v --basetemp=<scratch>

This is the evidence that Batfish parses configuration captured by this
application. Fixture-based tests cannot establish that.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.analysis.client import build_backend
from app.analysis.snapshot_builder import batfish_hostname
from app.core.config import Settings

pytestmark = pytest.mark.analysis

_ENABLED = os.environ.get("RUN_ANALYSIS_TESTS") == "1"


@pytest.mark.skipif(not _ENABLED, reason="Set RUN_ANALYSIS_TESTS=1 to enable")
def test_batfish_parses_a_snapshot_captured_by_this_application(
    settings: Settings, tmp_path: Path
) -> None:
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "cisco_iosxe"
        / "running_config.txt"
    )
    config = fixture.read_text(encoding="utf-8")
    hostname = batfish_hostname(config, fallback="fixture-device")
    backend = build_backend(settings)

    backend.init_snapshot("terraformer-optin", {hostname: config}, [])

    assert backend.snapshot_exists("terraformer-optin")
    findings = backend.parse_findings("terraformer-optin")
    unparsed = [
        item
        for item in findings
        if item.category.value == "parse_warning" and "cannot" in item.detail.lower()
    ]
    assert not unparsed, f"Batfish could not parse the configuration: {unparsed[:3]}"

    properties = backend.interface_properties("terraformer-optin")
    assert properties, "Batfish parsed no interfaces from the configuration"
```

- [ ] **Step 3: Run the opt-in test against a real container**

Start the profile:
```bash
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.analysis.yml --profile analysis up --build --detach --wait
```

Install the optional dependency into the local virtualenv, then run:
```bash
cd backend && RUN_ANALYSIS_TESTS=1 BATFISH_HOST=127.0.0.1 .venv/Scripts/python.exe -m pytest tests/analysis -v --basetemp=<scratch>
```

Because the `analysis` network is `internal: true`, Batfish is not reachable from the host. For this test either add a temporary host port to the batfish service, or run pytest inside the api container. Prefer running it inside the container: it exercises the real path and does not weaken the network boundary.

```bash
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.analysis.yml --profile analysis exec api python -m pytest tests/analysis -v
```

This requires the test files and the optional dependency inside the image. Add a build stage or install step for that, or accept the temporary host port for validation only and remove it before committing. Record which approach was used.

Expected: the test passes, or it fails with concrete parse warnings. **A failure here is a real finding, not a broken test** — it means Batfish cannot parse configuration this application captures, which is exactly what this task exists to discover. Record the outcome either way.

- [ ] **Step 4: Record the result**

Add a row to the verification record table in `docs/IMPLEMENTATION_STATUS.md` stating: the date, that the scope was the opt-in real-Batfish parse test, the exact command, and the outcome including **the device count reached**. Describe the 200-device bound as enforced but untested, per the design spec §8.4. Do not write that the feature supports 200 devices or campus scale.

Add to the Known gaps section:

```markdown
- Read-only configuration analysis is optional and off by default. It is
  Cisco IOS/IOS-XE only; Fortinet and generic devices are reported as
  exclusions. Its device and findings limits are enforced bounds that protect
  the host, not evidence of capacity: the recorded validation reached a small
  number of nodes, and everything above that is unverified. Measured capacity
  belongs to Phase 7.
```

- [ ] **Step 5: Update the capability matrix**

Add a section to `docs/CAPABILITY_MATRIX.md` after "Structured read capabilities":

```markdown
## Read-only analysis capabilities

Analysis derives conclusions from stored configuration. Results are labelled
`INFERRED` and are only as complete as the configuration set supplied. It is not
a device capability: no device is contacted.

| Capability | Cisco IOS/IOS-XE | Juniper Junos | Fortinet FortiOS | Generic/unknown |
|---|---|---|---|---|
| Configuration parse and hygiene findings | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| Path check (logical traceroute) | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| Filter/ACL check | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| Topology drift against observed neighbours | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |

Analysis requires the optional Compose profile and `ANALYSIS_ENABLED`. Both are
off by default. The enforced device bound is not a supported capacity.
```

- [ ] **Step 6: Update architecture and safety docs**

In `docs/architecture.md`, after the Telnet section, add the analysis data path: browser to `api`, `api`/`worker` to `batfish` on the `analysis` network, noting `internal: true`, no published port, no secrets, sanitized configuration only, and that Batfish never contacts a device.

In `docs/safety-model.md`, add a short subsection stating that analysis is read-only and outside Safety Levels A–D because it performs no device operation at all; that only sanitized configuration leaves the database; that findings text is sanitized again before storage because Batfish quotes configuration lines; and that a result's completeness disclosure is part of the result, not decoration.

In `README.md`, add the command to start the analysis profile and a one-line statement that it is optional, off by default, and read-only.

- [ ] **Step 7: Run every check**

```bash
cd backend && .venv/Scripts/python.exe -m ruff check --no-cache . && .venv/Scripts/pyright.exe && .venv/Scripts/python.exe -m pytest -q --basetemp=<scratch>
cd ../frontend && npm run typecheck && npm run lint && npm test -- --run && npm run build
cd .. && docker compose --env-file .env.example -f deploy/compose.yml -f deploy/compose.analysis.yml config --quiet
```
Expected: all pass. The opt-in analysis tests skip without `RUN_ANALYSIS_TESTS=1`.

- [ ] **Step 8: Stop the stack and commit**

```bash
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.analysis.yml --profile analysis down
```

Use `down` without `-v` so volumes survive.

```bash
git add backend/tests/analysis backend/pyproject.toml .env.example \
  docs/IMPLEMENTATION_STATUS.md docs/CAPABILITY_MATRIX.md docs/architecture.md \
  docs/safety-model.md README.md
git commit -m "test: validate Batfish against real captured configuration

Adds the opt-in analysis marker and a test that parses a configuration this
application captured, which fixture tests cannot establish. Records the device
count reached and documents the device bound as enforced but untested; measured
capacity remains a Phase 7 concern."
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| §2 optional profile, disabled by default | 1 (setting), 3 (profile) |
| §2 latest snapshot per device, re-parse action | 2 (builder), 5 (job), 8 (button) |
| §2 sanitized configuration only | 2, 5 (asserted in integration test) |
| §2 RQ job | 5 |
| §2 Cisco only | 2 (`SUPPORTED_VENDORS`) |
| §2 `INFERRED` labelling | 5 (schemas), 8 (UI test) |
| §2 mandatory completeness | 5 (view), 8 (shared component + test) |
| §2 parse once, query many | 5 (init), 7 (queries) |
| §3 four questions | 4, 5 (Q2), 6 (Q4), 7 (Q1, Q3) |
| §3.1 layer-1 topology as input | 2 (`_layer1_edges`), 3 (`init_snapshot`), 6 (scoped drift) |
| §4.1 internal network, no secrets/ports | 3 |
| §4.2 module layout | 2, 3, 4, 6 |
| §4.3 `ANALYSIS_ENABLED` | 1 |
| §4.4 optional dependency, lazy import | 3 |
| §5 three tables | 1 |
| §5 sanitize `detail` | 4 |
| §6.1 init flow | 5, 6 |
| §6.2 query flow | 7 |
| §6.3 expired, no hidden re-parse | 7 (service + test), 8 (button) |
| §7 trust model and copy rules | 8 (tests assert wording) |
| §8.1 exact-IPv4 validation | 7 |
| §8.2 every typed error | 1 (classes), 3, 5, 7 (raised and tested) |
| §8.2 partial parse does not fail the job | 4 (findings carry parse warnings), 5 |
| §8.3 limits, one job at a time, retention | 1 (settings), 4 (`prune`), 5 (retention test) |
| §8.4 bounds are not capacity claims | 9 |
| §9 testing approach | 3 (fake), 4, 6 (unit), 5, 7 (integration), 9 (opt-in) |
| §10 success criteria 1–7 | 5, 7, 8, 9 |

**Gap found and closed:** §8.3 requires "one active analysis job at a time", which no task enforced. Fixed in Task 5 as Step 5b. The first draft added a bespoke check inside `AnalysisService`; reading the codebase showed `JobService.enqueue` already rejects a concurrent discovery via `JobRepository.has_active`, so Step 5b extends that single mechanism with a small table instead of introducing a parallel one.

Closing that gap exposed a second problem: with the row created in the API handler, a request rejected by the guard would leave an orphan `pending` snapshot. Task 5 now creates the row inside the job (`initialise_new`), and Steps 4, 5 and 6 were made consistent with that ordering.

**Placeholder scan:** no TBD or TODO. Two steps deliberately require the implementer to read existing code and match it — `DeviceRepository.list_neighbors` in Task 5 and the UI component props in Task 8 Step 6. Both name the exact file to check, so they are verification instructions, not deferred decisions.

**Type consistency:** `Layer1Edge` field names are identical in Tasks 2, 3 and 6. `RawFinding` is constructed positionally in Task 6's tests and by keyword in Task 3; both match the field order `category, hostname, structure_type, structure_name, detail, line_number`. `to_findings` returns `tuple[list[PreparedFinding], bool]` in Task 4 and is unpacked as two values in Task 5. `AnalysisBackend` method names match `FakeBatfishClient` exactly. `CompletenessView` is used by Tasks 5 and 7 with the same fields the Task 8 test fixture provides. `AnalysisService` exposes `initialise_new()` (job entry point), `initialise(id)` (re-parse of an existing row), `completeness(snapshot)`, `path_check(...)` and `filter_check(...)`; Task 5's API and job dispatch and Task 7's endpoints all use those names.

**Known risks the implementer should expect**

These are places where the plan's code is a best-effort mapping against a library whose exact response shape must be confirmed at implementation time. None is a deferred decision; each has a concrete verification step.

1. **pybatfish column names.** `parse_findings` and `interface_properties` in Task 3 assume column names such as `Struct_Type`, `Ref_Name`, `Switchport_Mode`. Confirm them by printing `question.answer().frame().columns` against a real container in Task 9, and adjust the mapping. The typed dataclasses do not change.
2. **`traceroute` result shape.** `TraceResult` parsing uses `getattr` against pybatfish trace objects. Confirm the attribute names the same way. If they differ, only `PyBatfishBackend.traceroute` changes.
3. **Batfish image tag.** Task 3 pins `batfish/allinone:2024.07.15.1341`; verify the tag exists and record whichever tag is used.
4. **Reaching Batfish from the host.** The `analysis` network is `internal: true`, so the Task 9 opt-in test must run inside a container or use a temporary host port that is removed before committing. Task 9 Step 3 states both options and requires recording which was used.
