# Phase 3 — Safe Configuration MVP (Interface Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first structured write path — interface description and admin-state changes on Cisco IOS/IOS-XE — through the full mandatory apply pipeline (Change Plan → Vendor Render → Validation → Snapshot → Diff/Risk → Confirmation → Per-device Lock → Apply → Post-check → Confirm/Rollback → Audit), gated off by default.

**Architecture:** A new `app/changes/` module mirrors the proven `app/analysis/` shape: pure-logic types and risk classification, driver-owned render/validate/apply/rollback, a service orchestrating the pipeline, a repository, Pydantic schemas, and a router. Preview is synchronous (read-only against the device); Apply runs through the existing RQ job system with a new per-device exclusivity lock.

**Tech Stack:** FastAPI + Pydantic v2, SQLAlchemy 2.0 + Alembic, Scrapli (`send_configs` for config-mode pushes), RQ, React + TypeScript + TanStack Query, pytest, Vitest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-09-phase-3-safe-configuration-design.md` — every requirement in it must map to a task below.
- `STRUCTURED_WRITES_ENABLED` defaults to `false`. No existing capability may be affected when it is off.
- `JobType.APPLY_CHANGE` (not `apply_change_plan`) — `jobs.type` is `VARCHAR(15)`, already sized for `analyze_network`; `apply_change` (12 chars) fits without a further widening migration. Confirm with `alembic check`, don't assume.
- Rollback is surgical: inverse commands computed once at render time from state read immediately before rendering. Never replay a full running-config.
- `previous_value`, `rendered_commands`, and `inverse_commands` are device-originated text and must go through `sanitize_text` (`app.core.logging`) before storage, same rule as Batfish findings.
- This slice is Cisco IOS/IOS-XE only, `interface_description` and `interface_admin_state` only. VLAN, static route, other vendors are explicitly out of scope (spec §3).
- Every new migration must leave `alembic check` reporting no drift, verified against real PostgreSQL, both upgrade and downgrade.
- Phase 3 is not done until Task 8's real GNS3/EVE-NG lab-device test has actually run and its outcome is recorded honestly in `docs/IMPLEMENTATION_STATUS.md` — enforced-but-untested is not the same as verified, per this project's established convention.

---

### Task 1: Settings, errors, enums, models, migration

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/errors.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/connection_gate.py`
- Create: `backend/migrations/versions/20260809_0009_change_plans.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Modify: `backend/tests/unit/test_config.py`

**Interfaces:**
- Produces: `Settings.structured_writes_enabled: bool`; error classes `StructuredWritesDisabledError`, `ChangeVendorUnsupportedError`, `ChangePlanNotDraftError`, `ChangePlanDeviceLockedError`; enums `ChangePlanStatus`, `ChangeRisk`, `ChangeType`, `SafetyLevel.BEST_EFFORT`, `JobType.APPLY_CHANGE`; models `ChangePlan`, `ChangeStep`; `ConnectionOperation.STRUCTURED_WRITE`.

- [ ] **Step 1: Write the failing migration/ORM-drift test**

Open `backend/tests/integration/test_migrations.py` and find `test_migrations_match_the_orm_models`. Add a new assertion block right after the existing device/analysis table checks (read the existing test first to match its exact style — it uses `alembic_check_result` or similar; match whatever fixture the existing test already uses). Add:

```python
def test_change_plan_tables_exist_after_upgrade(migrated_connection) -> None:
    inspector = sa.inspect(migrated_connection)
    table_names = set(inspector.get_table_names())
    assert "change_plans" in table_names
    assert "change_steps" in table_names
```

(Use whichever fixture name `test_migrations.py` already uses for an upgraded connection — check the top of the file for the exact fixture, e.g. `migrated_connection` or `upgraded_engine`; copy the exact name from an existing test in this file rather than guessing.)

- [ ] **Step 2: Run it to verify it fails**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py::test_change_plan_tables_exist_after_upgrade -v
```
Expected: FAIL — `change_plans` not in `table_names` (or a fixture/collection error if the ORM models don't exist yet; either failure mode is acceptable at this point).

- [ ] **Step 3: Add settings**

In `backend/app/core/config.py`, find where `analysis_enabled`/`telnet_enabled` are declared (near the end of the settings block) and add immediately after `telnet_enabled: bool = False`:

```python
    # Structured configuration writes. Off by default: this is the first code
    # path able to change a real device outside the explicitly unguarded
    # Direct Mode terminal escape hatches. Intentional defense in depth, not
    # a missing UI shortcut.
    structured_writes_enabled: bool = False
```

- [ ] **Step 4: Add error classes**

In `backend/app/core/errors.py`, add after the last `Analysis*Error` class:

```python
class StructuredWritesDisabledError(AppError):
    code = "structured_writes_disabled_by_policy"
    status_code = 403
    default_message = "Structured configuration writes are disabled by server policy"


class ChangeVendorUnsupportedError(AppError):
    code = "change_vendor_unsupported"
    status_code = 422
    default_message = "This device's vendor does not support structured changes yet"


class ChangePlanNotDraftError(ConflictError):
    code = "change_plan_not_draft"
    default_message = "This change plan is not in draft status and cannot be applied"


class ChangePlanDeviceLockedError(ConflictError):
    code = "change_plan_device_locked"
    default_message = "Another change is already being applied to this device"
```

- [ ] **Step 5: Add ConnectionOperation.STRUCTURED_WRITE**

In `backend/app/services/connection_gate.py`, find `class ConnectionOperation(StrEnum):` and add a new member:

```python
class ConnectionOperation(StrEnum):
    CONNECTION_TEST = "connection_test"
    STRUCTURED_READ = "structured_read"
    STRUCTURED_WRITE = "structured_write"
    TERMINAL = "terminal"
```

No other change needed in this file: `_rate_limit()` falls through to `return None, None` for any operation it doesn't explicitly branch on, which is the correct default for `STRUCTURED_WRITE` too — it is still subject to the general per-device/global connection concurrency admission, just no separate per-minute rate limit, matching `STRUCTURED_READ`'s current behavior exactly.

- [ ] **Step 6: Add enums and models**

In `backend/app/models/entities.py`, add after the `SafetyLevel` class:

```python
class SafetyLevel(StrEnum):
    READ_ONLY = "D"
    BEST_EFFORT = "C"
```

(This replaces the existing single-member `SafetyLevel` — modify in place, don't add a duplicate class.)

Add near `JobType`, inside its existing definition:

```python
class JobType(StrEnum):
    REFRESH_DEVICE = "refresh_device"
    CAPTURE_CONFIG = "capture_config"
    DISCOVER_SSH = "discover_ssh"
    RUN_DIAGNOSTIC = "run_diagnostic"
    ANALYZE_NETWORK = "analyze_network"
    APPLY_CHANGE = "apply_change"
```

Add new enums after `ExclusionReason`/`FindingCategory` (end of the analysis enum block):

```python
class ChangePlanStatus(StrEnum):
    DRAFT = "draft"
    APPLYING = "applying"
    APPLIED = "applied"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class ChangeRisk(StrEnum):
    LOW = "low"
    HIGH = "high"


class ChangeType(StrEnum):
    INTERFACE_DESCRIPTION = "interface_description"
    INTERFACE_ADMIN_STATE = "interface_admin_state"
```

Add new models after `AnalysisFinding` (end of file):

```python
class ChangePlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "change_plans"

    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[ChangePlanStatus] = mapped_column(
        enum_type(ChangePlanStatus, "change_plan_status"),
        nullable=False,
        default=ChangePlanStatus.DRAFT,
    )
    safety_level: Mapped[SafetyLevel] = mapped_column(
        enum_type(SafetyLevel, "safety_level"),
        nullable=False,
    )
    risk: Mapped[ChangeRisk] = mapped_column(
        enum_type(ChangeRisk, "change_risk"),
        nullable=False,
    )
    pre_change_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("config_snapshots.id", ondelete="RESTRICT"),
    )
    post_change_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("config_snapshots.id", ondelete="RESTRICT"),
    )
    failure_code: Mapped[str | None] = mapped_column(String(100))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list[ChangeStep]] = relationship(
        back_populates="change_plan",
        cascade="all, delete-orphan",
        order_by="ChangeStep.created_at",
    )


class ChangeStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "change_steps"

    change_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("change_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    change_type: Mapped[ChangeType] = mapped_column(
        enum_type(ChangeType, "change_type"),
        nullable=False,
    )
    target: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_value: Mapped[str | None] = mapped_column(String(255))
    desired_value: Mapped[str] = mapped_column(String(255), nullable=False)
    rendered_commands: Mapped[str] = mapped_column(Text, nullable=False)
    inverse_commands: Mapped[str] = mapped_column(Text, nullable=False)

    change_plan: Mapped[ChangePlan] = relationship(back_populates="steps")
```

Check the top of `entities.py` for existing imports (`String`, `Text`, `DateTime`, `ForeignKey`, `relationship`, `Mapped`, `mapped_column`) — all are already imported for other models in this file; add nothing new to the import block unless one of these is genuinely missing (verify with a quick grep before assuming).

- [ ] **Step 7: Export new names**

In `backend/app/models/__init__.py`, add `ChangePlan`, `ChangeStep`, `ChangePlanStatus`, `ChangeRisk`, `ChangeType` to both the `from app.models.entities import (...)` block and the `__all__` list, alphabetically, matching how `AnalysisSnapshot` etc. were added in the prior phase.

- [ ] **Step 8: Write the migration**

Create `backend/migrations/versions/20260809_0009_change_plans.py`:

```python
"""Add change_plans and change_steps for structured configuration writes.

Revision ID: 20260809_0009
Revises: 20260808_0007
Create Date: 2026-08-09

Adds change_plans and change_steps: the first structured write capability's
data model (spec: docs/superpowers/specs/2026-08-09-phase-3-safe-configuration-design.md).

jobs.type is NOT widened here. The new JobType member is 'apply_change' (12
characters), which fits inside the existing VARCHAR(15) sizing (set in
20260808_0008 to fit 'analyze_network', 15 characters) without further
change. Confirmed by `alembic check` after this migration, not assumed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0009"
down_revision: str | None = "20260808_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_VALUES = ("draft", "applying", "applied", "failed", "rolled_back", "rollback_failed")
_RISK_VALUES = ("low", "high")
_TYPE_VALUES = ("interface_description", "interface_admin_state")
_SAFETY_VALUES = ("D", "C")


def _enum(name: str, values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=False)


def upgrade() -> None:
    op.create_table(
        "change_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "device_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("devices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", _enum("change_plan_status", _STATUS_VALUES), nullable=False),
        sa.Column("safety_level", _enum("safety_level", _SAFETY_VALUES), nullable=False),
        sa.Column("risk", _enum("change_risk", _RISK_VALUES), nullable=False),
        sa.Column(
            "pre_change_snapshot_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("config_snapshots.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "post_change_snapshot_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("config_snapshots.id", ondelete="RESTRICT"),
        ),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_change_plans_device_id", "change_plans", ["device_id"])

    op.create_table(
        "change_steps",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "change_plan_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("change_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("change_type", _enum("change_type", _TYPE_VALUES), nullable=False),
        sa.Column("target", sa.String(64), nullable=False),
        sa.Column("previous_value", sa.String(255)),
        sa.Column("desired_value", sa.String(255), nullable=False),
        sa.Column("rendered_commands", sa.Text(), nullable=False),
        sa.Column("inverse_commands", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_change_steps_change_plan_id", "change_steps", ["change_plan_id"])


def downgrade() -> None:
    op.drop_table("change_steps")
    op.drop_table("change_plans")
```

- [ ] **Step 9: Run the migration test again**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_migrations.py -v
```
Expected: all pass, including the new `test_change_plan_tables_exist_after_upgrade`.

- [ ] **Step 10: Verify against real PostgreSQL**

```bash
docker run -d --rm --name pg-phase3-check -e POSTGRES_PASSWORD=test -e POSTGRES_DB=terraformer -p 55440:5432 postgres:17.10-alpine3.23
# wait for ready (pg_isready), then:
cd backend
DATABASE_URL="postgresql+psycopg://postgres:test@127.0.0.1:55440/terraformer" .venv/Scripts/python.exe -m alembic upgrade head
DATABASE_URL="postgresql+psycopg://postgres:test@127.0.0.1:55440/terraformer" .venv/Scripts/python.exe -m alembic check
DATABASE_URL="postgresql+psycopg://postgres:test@127.0.0.1:55440/terraformer" .venv/Scripts/python.exe -m alembic downgrade base
docker stop pg-phase3-check
```
Expected: upgrade succeeds, `alembic check` reports "No new upgrade operations detected." (confirming the `jobs.type` width claim in this migration's docstring), downgrade succeeds.

- [ ] **Step 11: Add a settings unit test**

In `backend/tests/unit/test_config.py`, add (matching the style of the existing `analysis_enabled`/`telnet_enabled` default tests in this file):

```python
def test_structured_writes_disabled_by_default() -> None:
    assert Settings.model_fields["structured_writes_enabled"].default is False
```

- [ ] **Step 12: Run full backend suite and lint/type-check**

```bash
cd backend
.venv/Scripts/python.exe -m ruff check --no-cache .
.venv/Scripts/pyright.exe
.venv/Scripts/python.exe -m pytest -q --basetemp=<scratch>
```
Expected: ruff and pyright clean; all tests pass (same baseline count as before this task, plus the new migration/config tests).

- [ ] **Step 13: Commit**

```bash
git add backend/app/core/config.py backend/app/core/errors.py backend/app/models/entities.py \
  backend/app/models/__init__.py backend/app/services/connection_gate.py \
  backend/migrations/versions/20260809_0009_change_plans.py \
  backend/tests/integration/test_migrations.py backend/tests/unit/test_config.py
git commit -m "feat: add change plan settings, errors, data model, migration"
```

---

### Task 2: Pure logic — types and risk classification

**Files:**
- Create: `backend/app/changes/__init__.py`
- Create: `backend/app/changes/types.py`
- Create: `backend/app/changes/risk.py`
- Test: `backend/tests/unit/test_changes_risk.py`

**Interfaces:**
- Consumes: `ChangeType`, `ChangeRisk` from `app.models` (Task 1).
- Produces: `ChangeStepIntent(change_type, target, desired_value)`, `RenderedChange(commands, inverse_commands)` dataclasses; `classify_risk(change_type: ChangeType, *, current_admin_up: bool | None, current_oper_up: bool | None, desired_value: str) -> ChangeRisk`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_changes_risk.py`:

```python
from __future__ import annotations

from app.changes.risk import classify_risk
from app.models import ChangeRisk, ChangeType


def test_taking_admin_state_from_up_to_down_is_high_risk() -> None:
    risk = classify_risk(
        ChangeType.INTERFACE_ADMIN_STATE,
        current_admin_up=True,
        current_oper_up=True,
        desired_value="down",
    )
    assert risk is ChangeRisk.HIGH


def test_bringing_a_down_interface_up_is_low_risk() -> None:
    risk = classify_risk(
        ChangeType.INTERFACE_ADMIN_STATE,
        current_admin_up=False,
        current_oper_up=False,
        desired_value="up",
    )
    assert risk is ChangeRisk.LOW


def test_description_change_on_a_live_interface_is_high_risk() -> None:
    """Touching a currently up/forwarding interface is high risk regardless
    of change type -- description edits are usually harmless, but this is
    the signal that the interface carries live traffic right now."""
    risk = classify_risk(
        ChangeType.INTERFACE_DESCRIPTION,
        current_admin_up=True,
        current_oper_up=True,
        desired_value="uplink to core",
    )
    assert risk is ChangeRisk.HIGH


def test_description_change_on_a_down_interface_is_low_risk() -> None:
    risk = classify_risk(
        ChangeType.INTERFACE_DESCRIPTION,
        current_admin_up=False,
        current_oper_up=False,
        desired_value="spare port",
    )
    assert risk is ChangeRisk.LOW
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_changes_risk.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.changes'`.

- [ ] **Step 3: Create the module and types**

Create `backend/app/changes/__init__.py` (empty).

Create `backend/app/changes/types.py`:

```python
"""Pure, driver-agnostic value types for the change pipeline.

No I/O, no database session, no vendor knowledge -- keeps the pipeline's
shape testable without a device or a container.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import ChangeType


@dataclass(frozen=True, slots=True)
class ChangeStepIntent:
    """What the operator asked for, before rendering.

    Mirrors ChangeStep's pre-render fields as a plain in-memory value --
    not yet persisted, not yet rendered.
    """

    change_type: ChangeType
    target: str
    desired_value: str


@dataclass(frozen=True, slots=True)
class RenderedChange:
    commands: tuple[str, ...]
    inverse_commands: tuple[str, ...]
```

- [ ] **Step 4: Implement classify_risk**

Create `backend/app/changes/risk.py`:

```python
"""Risk classification for a single change step.

Deliberately narrow for this slice: a change is HIGH risk if it takes admin
state from up to down, or if it targets an interface that is currently up
(admin and operational) -- both are signals the interface carries live
traffic right now. Everything else is LOW. Not a general-purpose risk
engine; extend the conditions here as later Phase 3 slices add change types.
"""

from __future__ import annotations

from app.models import ChangeRisk, ChangeType


def classify_risk(
    change_type: ChangeType,
    *,
    current_admin_up: bool | None,
    current_oper_up: bool | None,
    desired_value: str,
) -> ChangeRisk:
    if change_type is ChangeType.INTERFACE_ADMIN_STATE and desired_value == "down":
        return ChangeRisk.HIGH
    if current_admin_up is True and current_oper_up is True:
        return ChangeRisk.HIGH
    return ChangeRisk.LOW
```

- [ ] **Step 5: Run to verify it passes**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_changes_risk.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 6: Lint and type-check**

```bash
cd backend && .venv/Scripts/python.exe -m ruff check --no-cache app/changes/ tests/unit/test_changes_risk.py
.venv/Scripts/pyright.exe app/changes/
```
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/changes/ backend/tests/unit/test_changes_risk.py
git commit -m "feat: add change pipeline types and risk classification"
```

---

### Task 3: Transport + driver interface — render/validate/apply/rollback for Cisco interface changes

**Files:**
- Modify: `backend/app/drivers/base.py`
- Modify: `backend/app/drivers/transport.py`
- Modify: `backend/app/drivers/cisco_iosxe.py`
- Modify: `backend/tests/fakes.py`
- Modify: `backend/tests/unit/test_drivers.py`

**Interfaces:**
- Consumes: `ChangeStepIntent`, `RenderedChange` (Task 2); `InterfaceFacts` (existing).
- Produces: `DeviceDriver.render_change(step, current) -> RenderedChange`, `.validate_change(step, current) -> list[str]`, `.apply_configuration(parameters, commands) -> None`, `.rollback(parameters, commands) -> None` (signature changed — was `rollback(parameters) -> None`, verified zero existing callers); `NetworkTransport.send_config(commands: Sequence[str]) -> str`.

- [ ] **Step 1: Write the failing driver tests**

Real Cisco IOS/IOS-XE config pushes need Scrapli's config-mode-aware `send_configs()` (confirmed via `inspect.signature` against the installed `scrapli.driver.core.cisco_iosxe.sync_driver.IOSXEDriver.send_configs`), not the existing exec-mode `send_command()` — this is why `NetworkTransport` gains a new method rather than reusing the old one.

Add to `backend/tests/unit/test_drivers.py`, near the existing `test_cisco_driver_is_read_only_and_closes_connections` test:

```python
def test_cisco_driver_renders_interface_description_change() -> None:
    factory = FakeTransportFactory(
        {"show interfaces": SANITIZED_SHOW_INTERFACES},
    )
    driver = CiscoIOSXEDriver(factory)
    current = driver.get_interfaces(parameters())
    target = next(iface for iface in current if iface.name == "GigabitEthernet1")

    step = ChangeStepIntent(
        change_type=ChangeType.INTERFACE_DESCRIPTION,
        target="GigabitEthernet1",
        desired_value="uplink-to-lab-core",
    )
    rendered = driver.render_change(step, target)

    assert rendered.commands == (
        "interface GigabitEthernet1",
        "description uplink-to-lab-core",
    )
    assert rendered.inverse_commands == (
        "interface GigabitEthernet1",
        f"description {target.description}",
    )


def test_cisco_driver_renders_interface_description_inverse_as_no_description_when_absent() -> None:
    factory = FakeTransportFactory({"show interfaces": SANITIZED_SHOW_INTERFACES})
    driver = CiscoIOSXEDriver(factory)
    current = InterfaceFacts(name="GigabitEthernet2", description=None, admin_up=True, oper_up=True)

    step = ChangeStepIntent(
        change_type=ChangeType.INTERFACE_DESCRIPTION,
        target="GigabitEthernet2",
        desired_value="new description",
    )
    rendered = driver.render_change(step, current)

    assert rendered.inverse_commands == ("interface GigabitEthernet2", "no description")


def test_cisco_driver_renders_admin_state_change_both_directions() -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    current = InterfaceFacts(name="GigabitEthernet1", description=None, admin_up=True, oper_up=True)

    down = driver.render_change(
        ChangeStepIntent(ChangeType.INTERFACE_ADMIN_STATE, "GigabitEthernet1", "down"),
        current,
    )
    assert down.commands == ("interface GigabitEthernet1", "shutdown")
    assert down.inverse_commands == ("interface GigabitEthernet1", "no shutdown")

    current_down = InterfaceFacts(name="GigabitEthernet1", description=None, admin_up=False, oper_up=False)
    up = driver.render_change(
        ChangeStepIntent(ChangeType.INTERFACE_ADMIN_STATE, "GigabitEthernet1", "up"),
        current_down,
    )
    assert up.commands == ("interface GigabitEthernet1", "no shutdown")
    assert up.inverse_commands == ("interface GigabitEthernet1", "shutdown")


def test_cisco_driver_validate_change_rejects_a_description_over_240_characters() -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    current = InterfaceFacts(name="GigabitEthernet1", description=None, admin_up=True, oper_up=True)
    step = ChangeStepIntent(ChangeType.INTERFACE_DESCRIPTION, "GigabitEthernet1", "x" * 241)

    issues = driver.validate_change(step, current)

    assert issues == ["description must be 240 characters or fewer"]


def test_cisco_driver_validate_change_accepts_a_valid_description() -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    current = InterfaceFacts(name="GigabitEthernet1", description=None, admin_up=True, oper_up=True)
    step = ChangeStepIntent(ChangeType.INTERFACE_DESCRIPTION, "GigabitEthernet1", "fine")

    assert driver.validate_change(step, current) == []


def test_cisco_driver_apply_configuration_sends_a_config_mode_batch() -> None:
    factory = FakeTransportFactory({})
    driver = CiscoIOSXEDriver(factory)

    driver.apply_configuration(
        parameters(), ["interface GigabitEthernet1", "description new-desc"]
    )

    assert factory.transports[0].sent_config_batches == [
        ["interface GigabitEthernet1", "description new-desc"]
    ]
    assert factory.transports[0].closed is True


def test_cisco_driver_apply_configuration_raises_typed_error_when_a_command_is_rejected() -> None:
    factory = FakeTransportFactory(
        {}, command_errors={"description new-desc": DriverCommandRejectedError()}
    )
    driver = CiscoIOSXEDriver(factory)

    with pytest.raises(DriverCommandRejectedError):
        driver.apply_configuration(
            parameters(), ["interface GigabitEthernet1", "description new-desc"]
        )
    assert factory.transports[0].closed is True


def test_cisco_driver_rollback_sends_the_inverse_commands() -> None:
    factory = FakeTransportFactory({})
    driver = CiscoIOSXEDriver(factory)

    driver.rollback(parameters(), ["interface GigabitEthernet1", "no shutdown"])

    assert factory.transports[0].sent_config_batches == [
        ["interface GigabitEthernet1", "no shutdown"]
    ]


def test_cisco_driver_capability_set_now_includes_write_capabilities() -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    for capability in (
        DriverCapability.RENDER,
        DriverCapability.VALIDATE,
        DriverCapability.APPLY,
        DriverCapability.POST_CHECK,
        DriverCapability.ROLLBACK,
    ):
        assert driver.capabilities.supports(capability)
    assert not driver.capabilities.supports(DriverCapability.COMPARE)
```

Update the existing test that this work deliberately makes false — find `test_cisco_driver_is_read_only_and_closes_connections` in `backend/tests/unit/test_drivers.py` and remove its two now-incorrect assertions:

```python
    assert not driver.capabilities.supports(DriverCapability.APPLY)
    ...
    with pytest.raises(UnsupportedCapabilityError):
        driver.apply_configuration(parameters(), ["interface GigabitEthernet1"])
```

(Delete both lines; the rest of that test — facts/neighbors/running-config read assertions — is untouched and still correct.)

Add the needed imports at the top of `test_drivers.py`:

```python
from app.changes.types import ChangeStepIntent
from app.drivers.base import InterfaceFacts
from app.models import ChangeType
```

Use the same `sanitized_outputs["show interfaces"]` fixture text already loaded by `conftest.py`'s `sanitized_outputs` fixture where a real parsed interface is needed — pass it via the `sanitized_outputs: dict[str, str]` fixture parameter and reference `sanitized_outputs["show interfaces"]` instead of a `SANITIZED_SHOW_INTERFACES` constant (match the existing fixture-based style already used elsewhere in this file rather than inventing a new module constant).

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_drivers.py -k "render_change or validate_change or apply_configuration or rollback or capability_set_now" -v
```
Expected: FAIL — `AttributeError` (methods don't exist yet) or `ImportError` (`app.changes.types` not wired into drivers yet).

- [ ] **Step 3: Extend NetworkTransport and FakeTransport with send_config**

In `backend/app/drivers/base.py`, extend the `NetworkTransport` Protocol:

```python
class NetworkTransport(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def send_command(self, command: str) -> str: ...

    def send_config(self, commands: Sequence[str]) -> str: ...
```

Add `Sequence` to the existing `from collections.abc import ...` import if not already present (check the top of the file first).

In `backend/tests/fakes.py`, extend `FakeTransport`:

```python
class FakeTransport(NetworkTransport):
    def __init__(
        self,
        commands: Mapping[str, str],
        *,
        open_error: Exception | None = None,
        command_error: Exception | None = None,
        command_errors: Mapping[str, Exception] | None = None,
    ) -> None:
        self.commands = dict(commands)
        self.open_error = open_error
        self.command_error = command_error
        self.command_errors = dict(command_errors or {})
        self.opened = False
        self.closed = False
        self.close_calls = 0
        self.sent_commands: list[str] = []
        self.sent_config_batches: list[list[str]] = []

    # ... existing open/close/send_command unchanged ...

    def send_config(self, commands: Sequence[str]) -> str:
        batch = list(commands)
        self.sent_config_batches.append(batch)
        for command in batch:
            self.sent_commands.append(command)
            if self.command_error is not None:
                raise self.command_error
            if command in self.command_errors:
                raise self.command_errors[command]
        return "\n".join(self.commands.get(command, "") for command in batch)
```

Only the `__init__` (add one field) and a new method are added; `open`/`close`/`send_command` are unchanged — verify with a diff that nothing else in this class moved.

- [ ] **Step 4: Implement ScrapliTransport.send_config**

In `backend/app/drivers/transport.py`, add to `ScrapliTransport` (right after `send_command`):

```python
    def send_config(self, commands: Sequence[str]) -> str:
        # send_configs (not send_command) enters/exits config mode itself and
        # reports per-line failure; stop_on_failed=True halts the batch on
        # the first rejected line rather than pushing the rest of a partial
        # change (confirmed against installed scrapli's IOSXEDriver.send_configs
        # signature: stop_on_failed defaults to False, so this must be explicit).
        response = self._connection.send_configs(list(commands), stop_on_failed=True)
        if response.failed:
            raise DriverCommandRejectedError()
        return str(response.result)
```

Add `Sequence` to this file's imports if not already present (check the top of `transport.py`).

`ScrapliGenericTransport` (the non-platform-specific transport used for generic/Fortinet devices) does NOT need `send_config` for this slice — only `CiscoIOSXEDriver` implements the write capabilities, so only `ScrapliTransport` (the Cisco-platform one) needs this method for now. Leave `ScrapliGenericTransport` untouched.

- [ ] **Step 5: Extend DeviceDriver ABC**

In `backend/app/drivers/base.py`, add the import at the top:

```python
from app.changes.types import ChangeStepIntent, RenderedChange
```

Change the existing `rollback` method and add two new ones (replace the existing `apply_configuration`/`rollback` block):

```python
    def render_change(self, step: ChangeStepIntent, current: InterfaceFacts) -> RenderedChange:
        del step, current
        self._unsupported(DriverCapability.RENDER)

    def validate_change(self, step: ChangeStepIntent, current: InterfaceFacts) -> list[str]:
        del step, current
        self._unsupported(DriverCapability.VALIDATE)

    def apply_configuration(self, parameters: ConnectionParameters, commands: list[str]) -> None:
        del parameters, commands
        self._unsupported(DriverCapability.APPLY)

    def rollback(self, parameters: ConnectionParameters, commands: list[str]) -> None:
        del parameters, commands
        self._unsupported(DriverCapability.ROLLBACK)
```

(`rollback`'s signature changes from `rollback(self, parameters) -> None` to `rollback(self, parameters, commands: list[str]) -> None` — confirmed zero existing callers in Task-3-prep verification, safe to change directly.)

- [ ] **Step 6: Implement Cisco's capability set, render/validate/apply/rollback**

In `backend/app/drivers/cisco_iosxe.py`, update the capability set in `__init__`:

```python
        self._capabilities = DriverCapabilitySet(
            supported=frozenset(
                {
                    DriverCapability.CONNECT,
                    DriverCapability.FACTS,
                    DriverCapability.INTERFACES,
                    DriverCapability.NEIGHBORS,
                    DriverCapability.RUNNING_CONFIG,
                    DriverCapability.ROUTING,
                    DriverCapability.ARP,
                    DriverCapability.MAC,
                    DriverCapability.PING,
                    DriverCapability.TRACEROUTE,
                    DriverCapability.RENDER,
                    DriverCapability.VALIDATE,
                    DriverCapability.APPLY,
                    DriverCapability.POST_CHECK,
                    DriverCapability.ROLLBACK,
                }
            ),
            safety_level=SafetyLevel.BEST_EFFORT,
        )
```

`DriverCapability.COMPARE` is deliberately omitted (spec §4.3: it names a native candidate-vs-running primitive Cisco IOS/IOS-XE doesn't have; the diff/risk stage is an application-level comparison, not a device operation).

Add the render/validate/apply/rollback methods (place after `get_running_config`, before `run_diagnostic`):

```python
    _DESCRIPTION_MAX_LENGTH = 240

    def render_change(self, step: ChangeStepIntent, current: InterfaceFacts) -> RenderedChange:
        if step.change_type is ChangeType.INTERFACE_DESCRIPTION:
            inverse_value = current.description
            inverse = (
                (f"interface {step.target}", f"description {inverse_value}")
                if inverse_value
                else (f"interface {step.target}", "no description")
            )
            return RenderedChange(
                commands=(f"interface {step.target}", f"description {step.desired_value}"),
                inverse_commands=inverse,
            )
        if step.change_type is ChangeType.INTERFACE_ADMIN_STATE:
            desired_up = step.desired_value == "up"
            current_up = bool(current.admin_up)
            return RenderedChange(
                commands=(
                    f"interface {step.target}",
                    "no shutdown" if desired_up else "shutdown",
                ),
                inverse_commands=(
                    f"interface {step.target}",
                    "no shutdown" if current_up else "shutdown",
                ),
            )
        self._unsupported(DriverCapability.RENDER)

    def validate_change(self, step: ChangeStepIntent, current: InterfaceFacts) -> list[str]:
        del current
        issues: list[str] = []
        if step.change_type is ChangeType.INTERFACE_DESCRIPTION:
            if len(step.desired_value) > self._DESCRIPTION_MAX_LENGTH:
                issues.append(
                    f"description must be {self._DESCRIPTION_MAX_LENGTH} characters or fewer"
                )
        elif step.change_type is ChangeType.INTERFACE_ADMIN_STATE:
            if step.desired_value not in ("up", "down"):
                issues.append("admin state must be 'up' or 'down'")
        return issues

    def apply_configuration(self, parameters: ConnectionParameters, commands: list[str]) -> None:
        transport = self._transport_factory(parameters)
        try:
            transport.open()
            transport.send_config(commands)
        finally:
            transport.close()

    def rollback(self, parameters: ConnectionParameters, commands: list[str]) -> None:
        transport = self._transport_factory(parameters)
        try:
            transport.open()
            transport.send_config(commands)
        finally:
            transport.close()
```

Add the needed imports at the top of `cisco_iosxe.py`:

```python
from app.changes.types import ChangeStepIntent, RenderedChange
from app.models import ChangeType
```

(Check existing imports first — `InterfaceFacts`, `DriverCapability`, `ConnectionParameters` are almost certainly already imported in this file since `get_interfaces`/`capabilities` already use them; add only what's missing.)

- [ ] **Step 7: Run to verify the new tests pass**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_drivers.py -v
```
Expected: all pass, including the updated `test_cisco_driver_is_read_only_and_closes_connections`.

- [ ] **Step 8: Lint and type-check**

```bash
cd backend
.venv/Scripts/python.exe -m ruff check --no-cache app/drivers/ tests/fakes.py tests/unit/test_drivers.py
.venv/Scripts/pyright.exe app/drivers/
```
Expected: clean.

- [ ] **Step 9: Run the full backend suite**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q --basetemp=<scratch>
```
Expected: all pass — this touches shared driver infrastructure (`GenericReadOnlyDriver` also extends `DeviceDriver`), so a full run (not just `test_drivers.py`) confirms nothing else broke.

- [ ] **Step 10: Commit**

```bash
git add backend/app/drivers/ backend/tests/fakes.py backend/tests/unit/test_drivers.py
git commit -m "feat: add Cisco interface change render, validate, apply, rollback"
```

---

### Task 4: Repository + schemas

**Files:**
- Create: `backend/app/repositories/changes.py`
- Create: `backend/app/schemas/changes.py`
- Test: `backend/tests/unit/test_changes_repository.py`

**Interfaces:**
- Consumes: `ChangePlan`, `ChangeStep`, `ChangePlanStatus`, `ChangeRisk`, `ChangeType`, `SafetyLevel` (Task 1).
- Produces: `ChangeRepository` (`create`, `get`, `list`, `set_status`, `add_step`, `list_by_device`); Pydantic `ChangePlanRequest`, `ChangeStepView`, `ChangePlanView`, `ApplyResponse`.

- [ ] **Step 1: Write the failing repository test**

Create `backend/tests/unit/test_changes_repository.py`. Check `backend/tests/unit/test_analysis_snapshot_builder.py` or an existing repository unit test for this project's session-fixture convention first (likely a `session` fixture backed by in-memory SQLite from `conftest.py`), then write:

```python
from __future__ import annotations

from uuid import uuid4

from app.models import ChangePlanStatus, ChangeRisk, ChangeType, Device, SafetyLevel, Vendor
from app.repositories.changes import ChangeRepository


def _device(session, address: str = "192.0.2.10"):
    from app.models import CredentialProfile, DeviceStatus, SSHCompatibility

    profile = CredentialProfile(
        name="test",
        username="user",
        encrypted_password=b"x",
        password_nonce=b"y",
    )
    session.add(profile)
    session.flush()
    device = Device(
        name=f"sw-{address}",
        management_address=address,
        port=22,
        vendor=Vendor.CISCO_IOSXE,
        ssh_compatibility=SSHCompatibility.MODERN,
        credential_profile_id=profile.id,
        status=DeviceStatus.UNREACHABLE,
    )
    session.add(device)
    session.flush()
    return device


def test_create_and_get_round_trips(session) -> None:
    device = _device(session)
    repo = ChangeRepository(session)

    plan = repo.create(
        device_id=device.id,
        safety_level=SafetyLevel.BEST_EFFORT,
        risk=ChangeRisk.LOW,
    )
    session.commit()

    fetched = repo.get(plan.id)
    assert fetched.device_id == device.id
    assert fetched.status is ChangePlanStatus.DRAFT


def test_add_step_and_list_by_device(session) -> None:
    device = _device(session)
    repo = ChangeRepository(session)
    plan = repo.create(device_id=device.id, safety_level=SafetyLevel.BEST_EFFORT, risk=ChangeRisk.LOW)
    session.flush()

    repo.add_step(
        plan,
        change_type=ChangeType.INTERFACE_DESCRIPTION,
        target="GigabitEthernet1",
        previous_value="old",
        desired_value="new",
        rendered_commands="interface GigabitEthernet1\ndescription new",
        inverse_commands="interface GigabitEthernet1\ndescription old",
    )
    session.commit()

    plans = repo.list_by_device(device.id)
    assert len(plans) == 1
    assert len(plans[0].steps) == 1
    assert plans[0].steps[0].target == "GigabitEthernet1"


def test_set_status_updates_failure_code_and_applied_at(session) -> None:
    device = _device(session)
    repo = ChangeRepository(session)
    plan = repo.create(device_id=device.id, safety_level=SafetyLevel.BEST_EFFORT, risk=ChangeRisk.LOW)
    session.commit()

    repo.set_status(plan, ChangePlanStatus.FAILED, failure_code="change_apply_failed")
    session.commit()

    fetched = repo.get(plan.id)
    assert fetched.status is ChangePlanStatus.FAILED
    assert fetched.failure_code == "change_apply_failed"


def test_get_raises_not_found_for_unknown_id(session) -> None:
    from app.core.errors import NotFoundError
    import pytest

    repo = ChangeRepository(session)
    with pytest.raises(NotFoundError):
        repo.get(uuid4())
```

Check `conftest.py` for the exact `session` fixture name/shape and the exact `Device`/`CredentialProfile` required-field set before finalizing this file — copy the device-creation helper pattern from an existing repository test (e.g. `test_analysis_snapshot_builder.py` or a device repository test) rather than guessing field names, since `CredentialProfile`'s exact encrypted-field names must match the real model precisely.

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_changes_repository.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.repositories.changes'`.

- [ ] **Step 3: Implement ChangeRepository**

Create `backend/app/repositories/changes.py`:

```python
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError
from app.models import ChangePlan, ChangePlanStatus, ChangeRisk, ChangeStep, ChangeType, SafetyLevel


class ChangeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, *, device_id: UUID, safety_level: SafetyLevel, risk: ChangeRisk
    ) -> ChangePlan:
        plan = ChangePlan(
            device_id=device_id,
            status=ChangePlanStatus.DRAFT,
            safety_level=safety_level,
            risk=risk,
        )
        self._session.add(plan)
        self._session.flush()
        return plan

    def add_step(
        self,
        plan: ChangePlan,
        *,
        change_type: ChangeType,
        target: str,
        previous_value: str | None,
        desired_value: str,
        rendered_commands: str,
        inverse_commands: str,
    ) -> ChangeStep:
        step = ChangeStep(
            change_plan_id=plan.id,
            change_type=change_type,
            target=target,
            previous_value=previous_value,
            desired_value=desired_value,
            rendered_commands=rendered_commands,
            inverse_commands=inverse_commands,
        )
        self._session.add(step)
        self._session.flush()
        return step

    def get(self, plan_id: UUID, *, for_update: bool = False) -> ChangePlan:
        statement = (
            select(ChangePlan)
            .where(ChangePlan.id == plan_id)
            .options(selectinload(ChangePlan.steps))
        )
        if for_update:
            statement = statement.with_for_update()
        plan = self._session.scalars(statement).one_or_none()
        if plan is None:
            raise NotFoundError("The requested change plan was not found")
        return plan

    def list_by_device(self, device_id: UUID, *, limit: int = 50) -> list[ChangePlan]:
        statement = (
            select(ChangePlan)
            .where(ChangePlan.device_id == device_id)
            .options(selectinload(ChangePlan.steps))
            .order_by(ChangePlan.created_at.desc())
            .limit(limit)
        )
        return list(self._session.scalars(statement))

    def set_status(
        self,
        plan: ChangePlan,
        status: ChangePlanStatus,
        *,
        failure_code: str | None = None,
    ) -> None:
        plan.status = status
        if failure_code is not None:
            plan.failure_code = failure_code

    def set_snapshots(
        self,
        plan: ChangePlan,
        *,
        pre_change_snapshot_id: UUID | None = None,
        post_change_snapshot_id: UUID | None = None,
    ) -> None:
        if pre_change_snapshot_id is not None:
            plan.pre_change_snapshot_id = pre_change_snapshot_id
        if post_change_snapshot_id is not None:
            plan.post_change_snapshot_id = post_change_snapshot_id
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_changes_repository.py -v
```
Expected: all pass.

- [ ] **Step 5: Write the schemas**

Create `backend/app/schemas/changes.py`:

```python
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.models import ChangePlanStatus, ChangeRisk, ChangeType, SafetyLevel
from app.schemas.common import APIModel


class ChangePlanRequest(APIModel):
    device_id: UUID
    change_type: ChangeType
    target: str
    desired_value: str


class ChangeStepView(APIModel):
    id: UUID
    change_type: ChangeType
    target: str
    previous_value: str | None
    desired_value: str
    rendered_commands: str
    inverse_commands: str


class ChangePlanView(APIModel):
    id: UUID
    device_id: UUID
    status: ChangePlanStatus
    safety_level: SafetyLevel
    risk: ChangeRisk
    failure_code: str | None
    applied_at: datetime | None
    steps: list[ChangeStepView]
    created_at: datetime
    updated_at: datetime
```

`ApplyResponse` is not a separate schema: applying returns a `JobView` (the existing job-status shape already used for `RUN_DIAGNOSTIC`/`ANALYZE_NETWORK`), not a new type — the caller polls `GET /api/jobs/{id}` the same way it already does for every other async device operation.

- [ ] **Step 6: Lint and type-check**

```bash
cd backend
.venv/Scripts/python.exe -m ruff check --no-cache app/repositories/changes.py app/schemas/changes.py tests/unit/test_changes_repository.py
.venv/Scripts/pyright.exe app/repositories/changes.py app/schemas/changes.py
```
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/repositories/changes.py backend/app/schemas/changes.py backend/tests/unit/test_changes_repository.py
git commit -m "feat: add change plan repository and schemas"
```

---

### Task 5: Preview service + API

**Files:**
- Create: `backend/app/changes/service.py`
- Create: `backend/app/api/changes.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/integration/test_changes_vertical_slice.py`

**Interfaces:**
- Consumes: `ChangeRepository` (Task 4), `SnapshotService` (existing), `DeviceService.admitted_connection` (existing), `classify_risk` (Task 2), `ChangeVendorUnsupportedError` (Task 1).
- Produces: `ChangeService.preview(device_id, change_type, target, desired_value) -> ChangePlan`; `POST /api/change-plans`, `GET /api/change-plans`, `GET /api/change-plans/{id}`.

- [ ] **Step 1: Write the failing vertical-slice test (preview only)**

Create `backend/tests/integration/test_changes_vertical_slice.py`. Model the device-registration helper on `test_analysis_vertical_slice.py`'s `_register_cisco` (same request shape, same fixtures: `authenticated_client`, `credential_profile`, `container`):

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import ApplicationContainer


def _register_cisco(client: TestClient, profile_id: str, address: str) -> str:
    connection = {
        "management_address": address,
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": profile_id,
        "ssh_compatibility": "modern",
    }
    candidate = client.post(
        "/api/ssh-host-key-candidates",
        json={key: value for key, value in connection.items() if key != "name"},
    )
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


def test_preview_returns_diff_risk_and_rendered_commands(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.10")

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_description",
            "target": "GigabitEthernet1",
            "desired_value": "uplink-to-lab-core",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["safety_level"] == "C"
    assert body["risk"] in ("low", "high")
    assert len(body["steps"]) == 1
    assert "description uplink-to-lab-core" in body["steps"][0]["rendered_commands"]


def test_preview_rejects_non_cisco_vendor(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = True
    profile_id = str(credential_profile["id"])
    connection = {
        "management_address": "192.0.2.20",
        "port": 22,
        "vendor": "generic",
        "credential_profile_id": profile_id,
        "ssh_compatibility": "modern",
    }
    candidate = authenticated_client.post("/api/ssh-host-key-candidates", json=connection)
    created = authenticated_client.post(
        "/api/devices",
        json={"name": "generic-box", **connection, "host_key_candidate_id": candidate.json()["id"]},
    )
    device_id = created.json()["id"]

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_description",
            "target": "eth0",
            "desired_value": "x",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "change_vendor_unsupported"


def test_every_endpoint_fails_closed_when_structured_writes_disabled(
    authenticated_client: TestClient,
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = False

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": "00000000-0000-0000-0000-000000000000",
            "change_type": "interface_description",
            "target": "GigabitEthernet1",
            "desired_value": "x",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "structured_writes_disabled_by_policy"
```

Check `tests/conftest.py` to confirm `authenticated_client`/`credential_profile`/`container` fixture names match exactly (they were used identically in `test_analysis_vertical_slice.py` this same repository already has — copy the exact fixture usage from there rather than re-deriving it).

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_changes_vertical_slice.py -v
```
Expected: FAIL — 404 (no `/api/change-plans` route registered yet).

- [ ] **Step 3: Implement ChangeService.preview**

Create `backend/app/changes/service.py`:

```python
"""Orchestrates the change pipeline's preview stage.

Apply (Task 6) lives in this same class, added in the next task -- preview
and apply share the repository and device-read plumbing, so splitting them
into separate classes would just be two constructors doing the same setup.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.changes.risk import classify_risk
from app.changes.types import ChangeStepIntent
from app.core.errors import ChangeVendorUnsupportedError, NotFoundError
from app.core.logging import sanitize_text
from app.core.config import Settings
from app.drivers import DriverRegistry
from app.models import ChangePlan, ChangeType, Device, SSHCompatibility, Vendor
from app.repositories.changes import ChangeRepository
from app.repositories.devices import DeviceRepository
from app.services.connection_gate import ConnectionOperation
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService

_SUPPORTED_VENDORS = frozenset({Vendor.CISCO_IOSXE})


class ChangeService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        drivers: DriverRegistry,
        devices: DeviceService,
        snapshots: SnapshotService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._drivers = drivers
        self._device_service = devices
        self._snapshots = snapshots
        self._changes = ChangeRepository(session)
        self._devices = DeviceRepository(session)

    def preview(
        self, *, device_id: UUID, change_type: ChangeType, target: str, desired_value: str
    ) -> ChangePlan:
        device = self._devices.get(device_id)
        if device.vendor not in _SUPPORTED_VENDORS:
            raise ChangeVendorUnsupportedError()

        driver = self._drivers.get(device.vendor)
        with self._device_service.admitted_connection(
            device_id=device.id,
            host=device.management_address,
            port=device.port,
            profile_id=device.credential_profile_id,
            vendor=device.vendor,
            compatibility=device.ssh_compatibility,
            group1_risk_acknowledged=(
                device.ssh_compatibility is SSHCompatibility.CISCO_LEGACY_GROUP1
            ),
            operation=ConnectionOperation.STRUCTURED_READ,
        ) as parameters:
            interfaces = driver.get_interfaces(parameters)
        current = next((iface for iface in interfaces if iface.name == target), None)
        if current is None:
            raise NotFoundError(f"Interface {target} was not found on this device")

        step = ChangeStepIntent(change_type=change_type, target=target, desired_value=desired_value)
        rendered = driver.render_change(step, current)
        issues = driver.validate_change(step, current)
        if issues:
            from app.core.errors import AppError

            raise AppError("The rendered change failed validation", details={"issues": issues})

        pre_snapshot = self._snapshots.capture(device.id)

        previous_value = (
            current.description if change_type is ChangeType.INTERFACE_DESCRIPTION
            else ("up" if current.admin_up else "down")
        )
        risk = classify_risk(
            change_type,
            current_admin_up=current.admin_up,
            current_oper_up=current.oper_up,
            desired_value=desired_value,
        )

        plan = self._changes.create(
            device_id=device.id,
            safety_level=driver.capabilities.safety_level,
            risk=risk,
        )
        self._changes.set_snapshots(plan, pre_change_snapshot_id=pre_snapshot.id)
        self._changes.add_step(
            plan,
            change_type=change_type,
            target=target,
            previous_value=sanitize_text(previous_value) if previous_value else previous_value,
            desired_value=desired_value,
            rendered_commands=sanitize_text("\n".join(rendered.commands)),
            inverse_commands=sanitize_text("\n".join(rendered.inverse_commands)),
        )
        self._session.commit()
        return self._changes.get(plan.id)

    def get(self, plan_id: UUID) -> ChangePlan:
        return self._changes.get(plan_id)

    def list_for_device(self, device_id: UUID) -> list[ChangePlan]:
        return self._changes.list_by_device(device_id)
```

`AppError` for validation issues is imported inline to avoid a circular import at module load time if `app.core.errors` doesn't already import cleanly at the top — check whether `app.core.errors.AppError` can be a top-level import instead (it almost certainly can, since other services import it at the top); if so, move it to the top-level import block instead of the inline import.

- [ ] **Step 4: Implement the API router**

Create `backend/app/api/changes.py`:

```python
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import Authenticated, ContainerDependency, SessionDependency
from app.changes.service import ChangeService
from app.core.errors import StructuredWritesDisabledError
from app.schemas.changes import ChangePlanRequest, ChangePlanView
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService


def _require_enabled(container: ContainerDependency) -> None:
    if not container.settings.structured_writes_enabled:
        raise StructuredWritesDisabledError()


router = APIRouter(
    prefix="/change-plans",
    tags=["changes"],
    dependencies=[Depends(_require_enabled)],
)


def _service(session: SessionDependency, container: ContainerDependency) -> ChangeService:
    devices = DeviceService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
    )
    return ChangeService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        devices=devices,
        snapshots=SnapshotService(
            session,
            store=container.snapshot_store,
            devices=devices,
            drivers=container.drivers,
        ),
    )


@router.post("", response_model=ChangePlanView, status_code=status.HTTP_201_CREATED)
def preview_change(
    request: ChangePlanRequest,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    plan = _service(session, container).preview(
        device_id=request.device_id,
        change_type=request.change_type,
        target=request.target,
        desired_value=request.desired_value,
    )
    return plan


@router.get("/{change_plan_id}", response_model=ChangePlanView)
def get_change_plan(
    change_plan_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).get(change_plan_id)


@router.get("", response_model=list[ChangePlanView])
def list_change_plans(
    device_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    return _service(session, container).list_for_device(device_id)
```

Register in `backend/app/api/router.py`:

```python
from app.api import (
    analysis,
    changes,
    credentials,
    devices,
    diagnostics,
    discovery,
    events,
    health,
    jobs,
    setup,
    snapshots,
    ssh_trust,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(setup.router)
api_router.include_router(credentials.router)
api_router.include_router(devices.router)
api_router.include_router(diagnostics.router)
api_router.include_router(discovery.router)
api_router.include_router(snapshots.router)
api_router.include_router(ssh_trust.router)
api_router.include_router(analysis.router)
api_router.include_router(changes.router)
api_router.include_router(events.router)
api_router.include_router(jobs.router)
```

(Insert `changes` into the import tuple alphabetically, and `api_router.include_router(changes.router)` right after the `analysis` line — matches the existing ordering convention in this file.)

- [ ] **Step 5: Run to verify it passes**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_changes_vertical_slice.py -v
```
Expected: all 3 pass.

- [ ] **Step 6: Lint and type-check**

```bash
cd backend
.venv/Scripts/python.exe -m ruff check --no-cache app/changes/ app/api/changes.py app/api/router.py tests/integration/test_changes_vertical_slice.py
.venv/Scripts/pyright.exe app/changes/ app/api/changes.py
```
Expected: clean.

- [ ] **Step 7: Run the full backend suite**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q --basetemp=<scratch>
```
Expected: all pass, no regressions.

- [ ] **Step 8: Commit**

```bash
git add backend/app/changes/service.py backend/app/api/changes.py backend/app/api/router.py \
  backend/tests/integration/test_changes_vertical_slice.py
git commit -m "feat: add change plan preview service and API"
```

---

### Task 6: Apply service + device-scoped lock + job + apply API endpoint

**Files:**
- Modify: `backend/app/repositories/jobs.py`
- Modify: `backend/app/services/jobs.py`
- Modify: `backend/app/changes/service.py`
- Modify: `backend/app/jobs/tasks.py`
- Modify: `backend/app/api/changes.py`
- Modify: `backend/tests/integration/test_changes_vertical_slice.py`
- Create: `backend/tests/unit/test_jobs_device_scoped_lock.py`

**Interfaces:**
- Consumes: `ChangeService.preview` (Task 5), `JobType.APPLY_CHANGE` (Task 1).
- Produces: `JobRepository.has_active(job_type, *, device_id=None) -> bool`; `ChangeService.apply(plan_id) -> dict`; `POST /api/change-plans/{id}/apply`.

- [ ] **Step 1: Write the failing device-scoped lock test**

Create `backend/tests/unit/test_jobs_device_scoped_lock.py`. Base the fixture setup on whatever `session`/device-creation helper `test_changes_repository.py` (Task 4) already established — reuse that exact helper rather than writing a third copy:

```python
from __future__ import annotations

from app.models import JobState, JobType
from app.repositories.jobs import JobRepository
from tests.unit.test_changes_repository import _device  # reuse the Task 4 helper


def test_has_active_is_global_by_default(session) -> None:
    device = _device(session)
    repo = JobRepository(session)
    repo.add(job_type=JobType.APPLY_CHANGE, device_id=device.id, input_data=None)
    session.commit()

    assert repo.has_active(JobType.APPLY_CHANGE) is True


def test_has_active_can_scope_to_one_device(session) -> None:
    device_a = _device(session, "192.0.2.10")
    device_b = _device(session, "192.0.2.11")
    repo = JobRepository(session)
    repo.add(job_type=JobType.APPLY_CHANGE, device_id=device_a.id, input_data=None)
    session.commit()

    assert repo.has_active(JobType.APPLY_CHANGE, device_id=device_a.id) is True
    assert repo.has_active(JobType.APPLY_CHANGE, device_id=device_b.id) is False
```

(If `_device` in `test_changes_repository.py` is a module-private helper not meant for cross-file import, move it into `tests/conftest.py` as a shared fixture instead — check which convention this codebase already follows for shared test device-creation helpers before choosing; `test_analysis_vertical_slice.py`'s `_register_cisco` suggests per-file helpers are the norm for API-level tests, but this is a lower-level repository test, so a `conftest.py` fixture may fit better. Match whichever pattern already exists for unit-level device fixtures.)

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_jobs_device_scoped_lock.py -v
```
Expected: FAIL — `TypeError: has_active() got an unexpected keyword argument 'device_id'`.

- [ ] **Step 3: Extend JobRepository.has_active**

In `backend/app/repositories/jobs.py`, change:

```python
    def has_active(self, job_type: JobType, *, device_id: UUID | None = None) -> bool:
        statement = (
            select(Job.id)
            .where(
                Job.type == job_type,
                Job.state.in_((JobState.QUEUED, JobState.STARTED)),
            )
            .limit(1)
        )
        if device_id is not None:
            statement = statement.where(Job.device_id == device_id)
        return self._session.scalar(statement) is not None
```

Add `from uuid import UUID` to this file's imports if not already present (check the top of the file first — `JobRepository.get`/`add` almost certainly already import `UUID`).

- [ ] **Step 4: Run to verify it passes**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_jobs_device_scoped_lock.py -v
```
Expected: both pass.

- [ ] **Step 5: Extend JobService with device-scoped exclusivity**

In `backend/app/services/jobs.py`, add a second exclusivity table alongside the existing one and branch on it in `enqueue`:

```python
_EXCLUSIVE_JOB_TYPES = {
    JobType.DISCOVER_SSH: "A discovery job is already active",
    JobType.ANALYZE_NETWORK: "An analysis job is already active",
}

# Job types that must not run concurrently with themselves ON THE SAME DEVICE,
# but may run in parallel across different devices -- unlike the global table
# above, applying a change to device A must never block device B.
_DEVICE_EXCLUSIVE_JOB_TYPES = {
    JobType.APPLY_CHANGE: "A change is already being applied to this device",
}
```

Update `enqueue`:

```python
    def enqueue(
        self,
        *,
        job_type: JobType,
        device_id: UUID | None = None,
        input_data: dict[str, object] | None = None,
    ) -> Job:
        if job_type in _EXCLUSIVE_JOB_TYPES and self._jobs.has_active(job_type):
            raise ConflictError(_EXCLUSIVE_JOB_TYPES[job_type])
        if (
            job_type in _DEVICE_EXCLUSIVE_JOB_TYPES
            and device_id is not None
            and self._jobs.has_active(job_type, device_id=device_id)
        ):
            raise ConflictError(_DEVICE_EXCLUSIVE_JOB_TYPES[job_type])
        if device_id is not None:
            self._devices.get(device_id)
        job = self._jobs.add(
            job_type=job_type,
            device_id=device_id,
            input_data=input_data,
        )
        # ... rest of the method unchanged ...
```

- [ ] **Step 6: Write the failing apply/rollback integration tests**

Add to `backend/tests/integration/test_changes_vertical_slice.py`:

```python
from app.jobs import tasks
from app.models import ChangePlanStatus


def _preview(client: TestClient, device_id: str, target: str = "GigabitEthernet1") -> dict:
    response = client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_description",
            "target": target,
            "desired_value": "new-description",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_successful_apply_reaches_applied_status(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.10")
    plan = _preview(authenticated_client, device_id)

    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    assert queued.status_code == 202, queued.text
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    fetched = authenticated_client.get(f"/api/change-plans/{plan['id']}")
    assert fetched.json()["status"] == "applied"
    assert fetched.json()["applied_at"] is not None


def test_apply_failure_triggers_rollback(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.11")
    plan = _preview(authenticated_client, device_id)

    from app.core.errors import DriverCommandRejectedError

    def failing_apply(self, parameters, commands):
        raise DriverCommandRejectedError()

    from app.drivers.cisco_iosxe import CiscoIOSXEDriver
    monkeypatch.setattr(CiscoIOSXEDriver, "apply_configuration", failing_apply)

    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    fetched = authenticated_client.get(f"/api/change-plans/{plan['id']}")
    assert fetched.json()["status"] == "rolled_back"


def test_apply_and_rollback_both_failing_lands_in_rollback_failed(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.12")
    plan = _preview(authenticated_client, device_id)

    from app.core.errors import DriverCommandRejectedError
    from app.drivers.cisco_iosxe import CiscoIOSXEDriver

    def failing(self, parameters, commands):
        raise DriverCommandRejectedError()

    monkeypatch.setattr(CiscoIOSXEDriver, "apply_configuration", failing)
    monkeypatch.setattr(CiscoIOSXEDriver, "rollback", failing)

    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    fetched = authenticated_client.get(f"/api/change-plans/{plan['id']}")
    assert fetched.json()["status"] == "rollback_failed"


def test_two_applies_to_the_same_device_conflict(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.13")
    plan_a = _preview(authenticated_client, device_id)
    plan_b = _preview(authenticated_client, device_id)

    first = authenticated_client.post(f"/api/change-plans/{plan_a['id']}/apply")
    assert first.status_code == 202, first.text
    second = authenticated_client.post(f"/api/change-plans/{plan_b['id']}/apply")

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "change_plan_device_locked"


def test_applies_to_different_devices_do_not_conflict(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = True
    profile_id = str(credential_profile["id"])
    device_a = _register_cisco(authenticated_client, profile_id, "192.0.2.14")
    device_b = _register_cisco(authenticated_client, profile_id, "192.0.2.15")
    plan_a = _preview(authenticated_client, device_a)
    plan_b = _preview(authenticated_client, device_b)

    first = authenticated_client.post(f"/api/change-plans/{plan_a['id']}/apply")
    second = authenticated_client.post(f"/api/change-plans/{plan_b['id']}/apply")

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text


def test_apply_on_a_non_draft_plan_is_rejected(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.16")
    plan = _preview(authenticated_client, device_id)
    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    second_apply = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")

    assert second_apply.status_code == 409
    assert second_apply.json()["error"]["code"] == "change_plan_not_draft"
```

Check how `FakeTransportFactory`/`FakeDriverRegistry` (or however this test suite's `container` fixture wires a fake Cisco transport for device connections in integration tests — look at how `test_analysis_vertical_slice.py`'s `_capture` helper connects without a real device) provides interface data for `get_interfaces()` during preview; the fixture container almost certainly already wires a fake transport returning the `sanitized_outputs` fixture text for `"show interfaces"` — confirm this exists and reuse it rather than building a new fake wiring path.

- [ ] **Step 7: Run to verify failure**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_changes_vertical_slice.py -v
```
Expected: FAIL — `/apply` endpoint doesn't exist (404) and `JobType.APPLY_CHANGE` isn't dispatched in `tasks.py` yet.

- [ ] **Step 8: Implement ChangeService.apply**

Add to `backend/app/changes/service.py` (append to `ChangeService`):

```python
    def apply(self, plan_id: UUID) -> dict[str, object]:
        from app.core.errors import AppError, ChangePlanNotDraftError

        plan = self._changes.get(plan_id, for_update=True)
        if plan.status is not ChangePlanStatus.DRAFT:
            raise ChangePlanNotDraftError()
        self._changes.set_status(plan, ChangePlanStatus.APPLYING)
        self._session.commit()

        device = self._devices.get(plan.device_id)
        driver = self._drivers.get(device.vendor)
        step = plan.steps[0]
        rendered_commands = step.rendered_commands.splitlines()
        inverse_commands = step.inverse_commands.splitlines()

        try:
            with self._device_service.admitted_connection(
                device_id=device.id,
                host=device.management_address,
                port=device.port,
                profile_id=device.credential_profile_id,
                vendor=device.vendor,
                compatibility=device.ssh_compatibility,
                group1_risk_acknowledged=(
                    device.ssh_compatibility is SSHCompatibility.CISCO_LEGACY_GROUP1
                ),
                operation=ConnectionOperation.STRUCTURED_WRITE,
            ) as parameters:
                driver.apply_configuration(parameters, rendered_commands)
                interfaces = driver.get_interfaces(parameters)
            current = next((iface for iface in interfaces if iface.name == step.target), None)
            post_check_ok = current is not None and (
                (step.change_type is ChangeType.INTERFACE_DESCRIPTION and current.description == step.desired_value)
                or (
                    step.change_type is ChangeType.INTERFACE_ADMIN_STATE
                    and current.admin_up == (step.desired_value == "up")
                )
            )
            if not post_check_ok:
                raise AppError("Post-check did not confirm the applied change")
        except AppError as error:
            return self._attempt_rollback(plan, device, driver, inverse_commands, error.code)

        post_snapshot = self._snapshots.capture(device.id)
        self._changes.set_snapshots(plan, post_change_snapshot_id=post_snapshot.id)
        self._changes.set_status(plan, ChangePlanStatus.APPLIED)
        plan.applied_at = utc_now()
        self._session.commit()
        return {"change_plan_id": str(plan.id), "status": plan.status.value}

    def _attempt_rollback(
        self, plan: ChangePlan, device: Device, driver, inverse_commands: list[str], failure_code: str
    ) -> dict[str, object]:
        try:
            with self._device_service.admitted_connection(
                device_id=device.id,
                host=device.management_address,
                port=device.port,
                profile_id=device.credential_profile_id,
                vendor=device.vendor,
                compatibility=device.ssh_compatibility,
                group1_risk_acknowledged=(
                    device.ssh_compatibility is SSHCompatibility.CISCO_LEGACY_GROUP1
                ),
                operation=ConnectionOperation.STRUCTURED_WRITE,
            ) as parameters:
                driver.rollback(parameters, inverse_commands)
            self._changes.set_status(plan, ChangePlanStatus.ROLLED_BACK, failure_code=failure_code)
        except Exception:
            self._changes.set_status(plan, ChangePlanStatus.ROLLBACK_FAILED, failure_code=failure_code)
        self._session.commit()
        return {"change_plan_id": str(plan.id), "status": plan.status.value}
```

Add `from app.core.time import utc_now` to the top-level imports of `service.py` (check `SnapshotService` or another service file for the exact import path — it's used as `utc_now()` elsewhere in this codebase per `TimestampMixin`).

A plan whose device is unreachable during `admitted_connection` itself (before `apply_configuration` is ever called) still goes through `_attempt_rollback`, which will also fail to connect and correctly land in `ROLLBACK_FAILED` — re-read spec §8.2's table: "Apply fails before any command reaches the device | plan → FAILED, no rollback attempted" describes the *design intent*, but this implementation cannot yet distinguish "never sent anything" from "sent something, then failed" without more granular error typing than `DriverCommandRejectedError`/connection errors currently provide. Accept this as a known simplification for this slice (rollback is attempted in both cases; on an unreachable device, both apply and the rollback attempt fail the same way, so the plan correctly lands in `ROLLBACK_FAILED` rather than `FAILED` even though nothing was actually sent) — note this explicitly in Task 8's documentation update rather than silently shipping a design/implementation mismatch.

- [ ] **Step 9: Wire the apply endpoint and job schema**

Add to `backend/app/schemas/changes.py`:

```python
class ChangeApplyJobInput(APIModel):
    change_plan_id: UUID
```

Add to `backend/app/api/changes.py`:

```python
from app.models import JobType
from app.schemas.changes import ChangeApplyJobInput, ChangePlanRequest, ChangePlanView
from app.schemas.jobs import JobView
from app.services.jobs import JobService


@router.post("/{change_plan_id}/apply", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
def apply_change_plan(
    change_plan_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    _service(session, container).get(change_plan_id)  # 404s early if the plan doesn't exist
    job_input = ChangeApplyJobInput(change_plan_id=change_plan_id)
    return JobService(session, container.queue).enqueue(
        job_type=JobType.APPLY_CHANGE,
        device_id=_service(session, container).get(change_plan_id).device_id,
        input_data=job_input.model_dump(mode="json"),
    )
```

(Two `_service(...).get(change_plan_id)` calls above are redundant — simplify to fetch the plan once and reuse it: replace the body with)

```python
@router.post("/{change_plan_id}/apply", response_model=JobView, status_code=status.HTTP_202_ACCEPTED)
def apply_change_plan(
    change_plan_id: UUID,
    _auth: Authenticated,
    session: SessionDependency,
    container: ContainerDependency,
):
    plan = _service(session, container).get(change_plan_id)
    job_input = ChangeApplyJobInput(change_plan_id=change_plan_id)
    return JobService(session, container.queue).enqueue(
        job_type=JobType.APPLY_CHANGE,
        device_id=plan.device_id,
        input_data=job_input.model_dump(mode="json"),
    )
```

- [ ] **Step 10: Wire the job dispatch**

In `backend/app/jobs/tasks.py`, add the branch after the `ANALYZE_NETWORK` branch:

```python
            elif job.type == JobType.APPLY_CHANGE and job.device_id is not None:
                from app.changes.service import ChangeService
                from app.schemas.changes import ChangeApplyJobInput

                apply_input = ChangeApplyJobInput.model_validate(job.input)
                changes = ChangeService(
                    session,
                    settings=container.settings,
                    drivers=container.drivers,
                    devices=devices,
                    snapshots=SnapshotService(
                        session,
                        store=container.snapshot_store,
                        devices=devices,
                        drivers=container.drivers,
                    ),
                )
                result = changes.apply(apply_input.change_plan_id)
```

Move the two inline imports (`ChangeService`, `ChangeApplyJobInput`) to the top-level import block of `tasks.py` instead, matching how `AnalysisService`/`DiagnosticJobInput` are already imported at the top of this file rather than inline — inline imports here would be inconsistent with the rest of the file.

- [ ] **Step 11: Run to verify tests pass**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/integration/test_changes_vertical_slice.py tests/unit/test_jobs_device_scoped_lock.py -v
```
Expected: all pass.

- [ ] **Step 12: Lint and type-check**

```bash
cd backend
.venv/Scripts/python.exe -m ruff check --no-cache .
.venv/Scripts/pyright.exe
```
Expected: clean. Fix any import-ordering or unused-import issues ruff reports from the moved inline imports.

- [ ] **Step 13: Run the full backend suite**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q --basetemp=<scratch>
```
Expected: all pass, no regressions in discovery/analysis exclusivity behavior (the global `_EXCLUSIVE_JOB_TYPES` path is unchanged, only a new parallel table was added).

- [ ] **Step 14: Commit**

```bash
git add backend/app/repositories/jobs.py backend/app/services/jobs.py backend/app/changes/service.py \
  backend/app/jobs/tasks.py backend/app/api/changes.py backend/app/schemas/changes.py \
  backend/tests/integration/test_changes_vertical_slice.py backend/tests/unit/test_jobs_device_scoped_lock.py
git commit -m "feat: add change plan apply, device-scoped locking, and job wiring"
```

---

### Task 7: Frontend — Configure tab

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/network.ts`
- Modify: `frontend/src/features/inventory/DeviceInspector.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/device-inspector.test.tsx`

**Interfaces:**
- Consumes: `POST /api/change-plans`, `GET /api/change-plans`, `POST /api/change-plans/{id}/apply` (Task 6).
- Produces: `ConfigureTab` component wired into `DeviceInspector`'s existing `InspectorTab` union.

- [ ] **Step 1: Write the failing component test**

Check `frontend/tests/device-inspector.test.tsx`'s existing structure (mock API setup, `render(<DeviceInspector .../>)` pattern) first, then add:

```typescript
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
// ... reuse this file's existing imports/render helper/mock device fixture ...

describe('Configure tab', () => {
  it('previews a change and shows the diff, risk, and rendered commands', async () => {
    server.use(
      // match this file's existing MSW (or equivalent) mock-server convention
      // for POST /api/change-plans returning a ChangePlanView-shaped body
    );
    renderInspector();
    await userEvent.click(screen.getByRole('tab', { name: 'Configure' }));

    await userEvent.selectOptions(screen.getByLabelText('Change type'), 'interface_description');
    await userEvent.selectOptions(screen.getByLabelText('Interface'), 'GigabitEthernet1');
    await userEvent.type(screen.getByLabelText('New description'), 'uplink-to-lab-core');
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => {
      expect(screen.getByText(/description uplink-to-lab-core/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Apply' })).toBeEnabled();
  });

  it('disables Apply until a plan has been previewed', async () => {
    renderInspector();
    await userEvent.click(screen.getByRole('tab', { name: 'Configure' }));

    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument();
  });
});
```

Match this test file's exact existing mock-server/fixture setup style (check whether it uses MSW, a hand-rolled `vi.fn()` mock of `api.*`, or something else — this project's other feature tests, e.g. `analysis-page.test.tsx`, established the convention to copy) rather than guessing a mocking library that may not be in use here.

- [ ] **Step 2: Run to verify it fails**

```bash
cd frontend && npm test -- --run tests/device-inspector.test.tsx
```
Expected: FAIL — no "Configure" tab exists yet.

- [ ] **Step 3: Add types**

In `frontend/src/types/api.ts`, add:

```typescript
export type ChangePlanStatus = 'draft' | 'applying' | 'applied' | 'failed' | 'rolled_back' | 'rollback_failed';
export type ChangeRisk = 'low' | 'high';
export type ChangeType = 'interface_description' | 'interface_admin_state';
export type SafetyLevel = 'D' | 'C';

export interface ChangeStep {
  id: string;
  change_type: ChangeType;
  target: string;
  previous_value: string | null;
  desired_value: string;
  rendered_commands: string;
  inverse_commands: string;
}

export interface ChangePlan {
  id: string;
  device_id: string;
  status: ChangePlanStatus;
  safety_level: SafetyLevel;
  risk: ChangeRisk;
  failure_code: string | null;
  applied_at: string | null;
  steps: ChangeStep[];
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 4: Add API client functions**

In `frontend/src/api/network.ts`, add to the `api` object (alongside the existing `analysisSnapshots`/`startAnalysis` entries):

```typescript
  previewChange: (input: {
    device_id: string;
    change_type: ChangeType;
    target: string;
    desired_value: string;
  }) => apiRequest<ChangePlan>('/change-plans', { method: 'POST', body: json(input) }),
  listChangePlans: (deviceId: string) =>
    apiRequest<ChangePlan[]>(`/change-plans?device_id=${encodeURIComponent(deviceId)}`),
  applyChangePlan: (id: string) =>
    apiRequest<Job>(`/change-plans/${encodeURIComponent(id)}/apply`, { method: 'POST' }),
```

Add `ChangePlan`, `ChangeType` to this file's existing type imports from `../types/api`.

- [ ] **Step 5: Implement ConfigureTab**

In `frontend/src/features/inventory/DeviceInspector.tsx`, add `'configure'` to the `InspectorTab` union (near `'overview'`):

```typescript
type InspectorTab =
  | 'overview'
  | 'interfaces'
  | 'neighbors'
  | 'diagnostics'
  | 'snapshots'
  | 'configure'
  | 'activity';
```

(Match this file's exact existing member list and ordering — read the current union first and insert `'configure'` in a sensible position, e.g. right after `'snapshots'`, rather than assuming the exact existing member names.)

Add the tab button entry (near `{ id: 'overview' as const, label: 'Overview', icon: CircleGauge }`):

```typescript
      { id: 'configure' as const, label: 'Configure', icon: Wrench },
```

Import `Wrench` (or another appropriate icon already available from `lucide-react`, matching this project's existing icon library) at the top of the file.

Add the `ConfigureTab` component (place near `SnapshotsTab`):

```typescript
function ConfigureTab({ device }: { device: Device }) {
  const queryClient = useQueryClient();
  const [changeType, setChangeType] = useState<ChangeType>('interface_description');
  const [target, setTarget] = useState('');
  const [desiredValue, setDesiredValue] = useState('');
  const [plan, setPlan] = useState<ChangePlan | null>(null);

  const preview = useMutation({
    mutationFn: () =>
      api.previewChange({
        device_id: device.id,
        change_type: changeType,
        target,
        desired_value: desiredValue,
      }),
    onSuccess: (result) => setPlan(result),
  });

  const apply = useMutation({
    mutationFn: (planId: string) => api.applyChangePlan(planId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['change-plans', device.id] });
    },
  });

  const history = useQuery({
    queryKey: ['change-plans', device.id],
    queryFn: () => api.listChangePlans(device.id),
  });

  return (
    <section className="inspector-section">
      <header>
        <h3>Configure</h3>
      </header>

      <div className="configure-form">
        <label>
          Change type
          <select
            aria-label="Change type"
            value={changeType}
            onChange={(event) => setChangeType(event.target.value as ChangeType)}
          >
            <option value="interface_description">Interface description</option>
            <option value="interface_admin_state">Interface admin state</option>
          </select>
        </label>
        <label>
          Interface
          <select aria-label="Interface" value={target} onChange={(event) => setTarget(event.target.value)}>
            <option value="">Select an interface</option>
            {device.interfaces?.map((iface) => (
              <option key={iface.name} value={iface.name}>
                {iface.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {changeType === 'interface_description' ? 'New description' : 'Desired admin state'}
          {changeType === 'interface_admin_state' ? (
            <select
              aria-label="Desired admin state"
              value={desiredValue}
              onChange={(event) => setDesiredValue(event.target.value)}
            >
              <option value="">Select</option>
              <option value="up">up</option>
              <option value="down">down</option>
            </select>
          ) : (
            <input
              aria-label="New description"
              value={desiredValue}
              onChange={(event) => setDesiredValue(event.target.value)}
            />
          )}
        </label>
        <Button
          onClick={() => preview.mutate()}
          busy={preview.isPending}
          disabled={target === '' || desiredValue === ''}
        >
          Preview
        </Button>
      </div>

      {plan === null ? null : (
        <div className="configure-preview">
          <Badge tone={plan.risk === 'high' ? 'warning' : 'success'}>{plan.risk} risk</Badge>
          <p className="configure-preview__safety">Safety level {plan.safety_level} — best effort, not auto-rollback</p>
          {plan.steps.map((step) => (
            <div key={step.id} className="configure-preview__step">
              <p>
                {step.target}: {step.previous_value ?? '(none)'} → {step.desired_value}
              </p>
              <pre>{step.rendered_commands}</pre>
            </div>
          ))}
          <Button variant="primary" onClick={() => apply.mutate(plan.id)} busy={apply.isPending}>
            Apply
          </Button>
        </div>
      )}

      {history.data === undefined || history.data.length === 0 ? null : (
        <div className="configure-history">
          <h4>Past changes</h4>
          {history.data.map((item) => (
            <div key={item.id} className="configure-history__item">
              <Badge
                tone={
                  item.status === 'applied'
                    ? 'success'
                    : item.status === 'rollback_failed'
                      ? 'danger'
                      : 'neutral'
                }
              >
                {item.status}
              </Badge>
              <span>{item.steps[0]?.target}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
```

Add the render branch near the other `{tab === '...' ? <...Tab .../> : null}` lines:

```typescript
        {tab === 'configure' ? <ConfigureTab device={device} /> : null}
```

Add `ChangePlan`, `ChangeType` to this file's type imports, and `useMutation`, `useQuery`, `useQueryClient` to its `@tanstack/react-query` import if not already present (check — `useMutation` is likely already imported for other tabs' actions).

Check `device.interfaces` — confirm the `Device` type actually carries a populated interfaces array by this point in the codebase (it may live on a separate `InterfacesTab`-only fetch instead). If `Device` does not already include `interfaces`, use the existing interfaces-fetching hook/query that `InterfacesTab` uses instead of assuming the field exists on `device` directly — check `InterfacesTab`'s implementation in this same file first.

- [ ] **Step 6: Add minimal CSS**

Append to `frontend/src/styles.css`:

```css
/* ---------------------------------------------------------------------------
   Configure tab
   --------------------------------------------------------------------------- */

.configure-form {
  display: grid;
  gap: 10px;
  max-width: 360px;
}

.configure-preview {
  margin-top: 16px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  display: grid;
  gap: 8px;
}

.configure-preview__step pre {
  background: var(--surface-muted);
  padding: 8px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 12px;
}

.configure-history {
  margin-top: 16px;
}

.configure-history__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
```

Use this project's existing CSS custom property names (`--border`, `--surface-muted`) — verified against the analysis-page CSS block added in the prior phase; don't invent new tokens.

- [ ] **Step 7: Run to verify tests pass**

```bash
cd frontend && npm test -- --run tests/device-inspector.test.tsx
```
Expected: both new tests pass.

- [ ] **Step 8: Typecheck, lint, full test run, build**

```bash
cd frontend
npm run typecheck
npm run lint
npm test -- --run
npm run build
```
Expected: all clean, no regressions in other DeviceInspector tab tests.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/network.ts frontend/src/features/inventory/DeviceInspector.tsx \
  frontend/src/styles.css frontend/tests/device-inspector.test.tsx
git commit -m "feat: add Configure tab for interface change preview and apply"
```

---

### Task 8: Real-lab validation and documentation

**Files:**
- Create: `backend/tests/lab/test_structured_writes_lab.py`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/safety-model.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no new code interface — this task is validation and honest recording, per the spec's Approved Decision 3 and Task 9's precedent from the Batfish plan.

- [ ] **Step 1: Write the opt-in lab test**

Check `backend/tests/lab/test_cisco_iosxe_lab.py` first (already established `RUN_LAB_TESTS=1` + `LAB_DEVICE_*` env var convention) and mirror it exactly:

```python
from __future__ import annotations

import os

import pytest

from app.core.config import Settings
from app.drivers import CiscoIOSXEDriver, ConnectionParameters
from app.drivers.transport import ScrapliTransportFactory
from app.changes.types import ChangeStepIntent
from app.models import ChangeType

pytestmark = [
    pytest.mark.lab,
    pytest.mark.skipif(
        os.getenv("RUN_LAB_TESTS") != "1",
        reason="Set RUN_LAB_TESTS=1 explicitly to enable read-only lab access",
    ),
]


def test_apply_and_rollback_an_interface_description_on_a_real_lab_device() -> None:
    """Requires LAB_DEVICE_* vars (see test_cisco_iosxe_lab.py) plus
    LAB_TARGET_INTERFACE naming a real, currently-unused interface on that
    device -- never point this at a live uplink."""
    required = (
        "LAB_DEVICE_HOST",
        "LAB_DEVICE_USERNAME",
        "LAB_DEVICE_PASSWORD",
        "LAB_KNOWN_HOSTS_FILE",
        "LAB_TARGET_INTERFACE",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing opt-in lab variables: {', '.join(missing)}")

    host = os.environ["LAB_DEVICE_HOST"]
    port = int(os.getenv("LAB_DEVICE_PORT", "22"))
    known_hosts = open(os.environ["LAB_KNOWN_HOSTS_FILE"], encoding="utf-8").read()
    entries = [line for line in known_hosts.splitlines() if line and not line.startswith("#")]
    target = os.environ["LAB_TARGET_INTERFACE"]

    driver = CiscoIOSXEDriver(ScrapliTransportFactory())
    parameters = ConnectionParameters(
        host=host,
        port=port,
        username=os.environ["LAB_DEVICE_USERNAME"],
        password=os.environ["LAB_DEVICE_PASSWORD"],
        known_hosts=entries[0] + "\n",
        enable_password=os.getenv("LAB_DEVICE_ENABLE_PASSWORD"),
        connect_timeout_seconds=10,
        command_timeout_seconds=30,
    )

    before = next(iface for iface in driver.get_interfaces(parameters) if iface.name == target)

    step = ChangeStepIntent(
        change_type=ChangeType.INTERFACE_DESCRIPTION,
        target=target,
        desired_value="terraformer-phase3-lab-check",
    )
    rendered = driver.render_change(step, before)
    assert driver.validate_change(step, before) == []

    driver.apply_configuration(parameters, list(rendered.commands))
    after = next(iface for iface in driver.get_interfaces(parameters) if iface.name == target)
    assert after.description == "terraformer-phase3-lab-check"

    driver.rollback(parameters, list(rendered.inverse_commands))
    restored = next(iface for iface in driver.get_interfaces(parameters) if iface.name == target)
    assert restored.description == before.description
```

- [ ] **Step 2: Run against a real GNS3/EVE-NG lab device**

```bash
cd backend
RUN_LAB_TESTS=1 LAB_DEVICE_HOST=<lab-ip> LAB_DEVICE_USERNAME=<user> LAB_DEVICE_PASSWORD=<pass> \
  LAB_KNOWN_HOSTS_FILE=<path> LAB_TARGET_INTERFACE=<a real, currently-unused interface name> \
  LAB_EXPECTED_PLATFORM=cisco_iosxe \
  .venv/Scripts/python.exe -m pytest tests/lab/test_structured_writes_lab.py -v
```

Expected: the test passes, applying and then rolling back a real interface description on real (or GNS3/EVE-NG virtual) Cisco hardware. **A failure here is a real finding, not a broken test** — it means the render/apply/rollback pipeline doesn't work against a real device, which is exactly what this task exists to discover. Record the outcome either way, per this plan's Global Constraints.

- [ ] **Step 3: Record the result honestly**

Add a row to the verification record table in `docs/IMPLEMENTATION_STATUS.md`, following the exact style of the Batfish real-container validation row: date, scope ("Phase 3 interface change: opt-in real-lab apply and rollback"), exact command used, and outcome — including whether it was run against physical hardware or a GNS3/EVE-NG virtual node, which interface/platform, and the literal result. If it did not run (no lab available yet), say so explicitly rather than omitting the row — do not claim Phase 3 is done if this step did not execute.

Add to the Known gaps section:

```markdown
- Structured configuration writes are optional (`STRUCTURED_WRITES_ENABLED`,
  off by default) and cover exactly two change types on Cisco IOS/IOS-XE
  only: interface description and admin state. VLAN, static route, other
  vendors, and any Safety Level above C remain Not Implemented. Rollback is
  surgical (inverse commands from the rendered change), never a full
  running-config replay. `ROLLBACK_FAILED` is a real, expected outcome of
  Level C and requires manual device verification when it occurs — it is
  not a bug class this phase attempts to eliminate. No re-validation is
  performed immediately before push; a plan applies exactly what it showed
  the operator at preview time, and post-check is the only safety net
  against device state that drifted since then.
```

- [ ] **Step 4: Update the capability matrix**

In `docs/CAPABILITY_MATRIX.md`, change the "Structured write capabilities" table's Cisco IOS/IOS-XE column for the rows this phase actually implements:

```markdown
| Render interface description/admin state | **Implemented, [lab verified / lab unverified per Step 3's actual result]** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Validate rendered commands | **Implemented, [same]** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Pre-change snapshot pipeline | **Implemented, [same]** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Apply configuration | **Implemented, [same]** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Post-change checks | **Implemented, [same]** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Rollback/assisted recovery | **Implemented, [same]** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
```

Fill in `[lab verified / lab unverified per Step 3's actual result]` with whichever is literally true after Step 2 ran — `Lab verified` only if Step 2's test actually passed against a real device; `Implemented, lab unverified` otherwise, matching this document's own status-definition table at its top. Update "Current structured-write safety classification for every platform: **Level D — Read-only**" to note Cisco IOS/IOS-XE interface changes are now Level C, all other platforms/capabilities remain D.

- [ ] **Step 5: Update the safety model doc**

In `docs/safety-model.md`, change the "Future mandatory apply pipeline" section header and lead-in to reflect that it is now real for one vendor/two change types — do not delete the pipeline diagram (it still documents the general shape for future Phase 3 slices), but add a sentence stating it is implemented, not merely planned, for Cisco IOS/IOS-XE interface description/admin-state changes as of this phase, with a pointer to the capability matrix row for the current, precise scope.

- [ ] **Step 6: Update README**

In `README.md`, add a short note near wherever `ANALYSIS_ENABLED`/`TELNET_ENABLED` are already documented: `STRUCTURED_WRITES_ENABLED` (off by default) gates the first structured write capability, scoped to Cisco IOS/IOS-XE interface description and admin-state changes.

- [ ] **Step 7: Run every check**

```bash
cd backend
.venv/Scripts/python.exe -m ruff check --no-cache .
.venv/Scripts/pyright.exe
.venv/Scripts/python.exe -m pytest -q --basetemp=<scratch>
cd ../frontend
npm run typecheck && npm run lint && npm test -- --run && npm run build
cd ..
docker compose --env-file .env.example -f deploy/compose.yml config --quiet
```
Expected: all pass. The opt-in lab test skips cleanly without `RUN_LAB_TESTS=1`.

- [ ] **Step 8: Commit**

```bash
git add backend/tests/lab/test_structured_writes_lab.py docs/IMPLEMENTATION_STATUS.md \
  docs/CAPABILITY_MATRIX.md docs/safety-model.md README.md
git commit -m "test: validate interface changes against a real lab device

Adds the opt-in lab test for apply-and-rollback of an interface description
change, and records the real outcome in the capability matrix and
implementation status docs rather than claiming Level C support without
having exercised it against a device."
```

---

## Self-Review

**Spec coverage:**
- §3 in-scope: data model/migration → Task 1; renderer/validator/inverse → Task 3; pipeline stages → Tasks 5–6; device-scoped locking → Task 6; both API endpoints + list/get → Tasks 5–6; Configure tab → Task 7; kill switch + SafetyLevel.BEST_EFFORT → Task 1; fixture tests + opt-in lab test → Tasks 1–8. All covered.
- §4.3 driver interface changes, including the `COMPARE` omission and the `rollback` signature change → Task 3.
- §5 data model, including the `jobs.type` width reasoning → Task 1.
- §6 flows (preview synchronous/no-lock, apply async/job-locked, vendor gate) → Tasks 5–6.
- §7 rollback semantics (surgical, `ROLLBACK_FAILED` as legitimate) → Task 6's implementation and Task 8's documentation.
- §8 error table → Task 1 (error classes) and Task 6 (where each is actually raised); §8.3's known limitation is called out explicitly in Task 6 Step 8 rather than silently implemented differently from the spec's stated intent.
- §9 testing, including the required opt-in lab test → Task 8.
- §10 success criteria 1–6 → covered by Tasks 5–7's automated tests; criterion 7 (real lab validation, recorded honestly) → Task 8.

**Placeholder scan:** an earlier draft of Task 6 Step 8 showed an intermediate stub (`pass` with a comment) before the real `apply()` body — removed during self-review since a worker reading that step in isolation could mistake it for something to keep. Every code step now shows only the complete, final content. No `TBD`/`TODO`/"add appropriate error handling"-style placeholders found elsewhere.

**Type consistency:** `ChangeStepIntent(change_type, target, desired_value)` (Task 2) is used identically in Task 3 (driver methods), Task 5 (`ChangeService.preview`), and Task 8 (lab test). `RenderedChange(commands, inverse_commands)` likewise. `ChangeRepository.get(plan_id, for_update=False)` (Task 4) is called with `for_update=True` in Task 6's `apply()` — verified consistent, since Task 4 declared `for_update` as a keyword parameter apply can pass. `JobRepository.has_active(job_type, *, device_id=None)` (Task 6) matches both call sites in `JobService.enqueue` (global check omits `device_id`, device-scoped check passes it).

**Known limitation surfaced, not hidden:** Task 6 Step 8 explicitly documents that this implementation cannot yet distinguish "apply never reached the device" from "apply reached the device and failed" as cleanly as spec §8.2's table implies — both currently attempt rollback. This is flagged inline in the plan and pointed at Task 8's documentation step rather than silently shipping a spec/implementation mismatch.
