# Phase 3 — Safe Configuration MVP Design

## 1. Context

Phases 0–2 built a read-only control workbench: manual device registration,
facts/interfaces/running-config capture, bounded discovery, a topology canvas,
a Direct Mode terminal, structured diagnostics, and (most recently) optional
read-only Batfish analysis. Every structured write capability is currently
**Not Implemented**, and every driver is Safety Level D — this is documented
and enforced, not an oversight (`docs/safety-model.md` §"Current enforcement
boundary").

`docs/network-automation-final-plan.md` §5/§7/§15 defines Phase 3 as the
project's first structured write path: a Change Plan and Cisco renderer for
Interface/VLAN/Static Route, diff/validation/risk/lock, explicit Apply,
post-check, and assisted rollback. This is the single highest-consequence
capability the application will ever gain — it is the first code path able to
change a real device's configuration outside the existing, explicitly
unguarded Direct Mode terminal escape hatches (SSH/Telnet/USB).

This spec covers only the first vertical slice of Phase 3: **interface
description and admin-state changes on Cisco IOS/IOS-XE**. VLAN and static
route support are later slices within the same phase, using the same
pipeline, once this slice is proven end-to-end including against a real lab
device.

## 2. Approved Decisions

Confirmed with the user before this design was written:

1. **Sequencing:** interface changes first, as a complete vertical slice
   through the full pipeline; VLAN and static route are fast-follow slices
   within Phase 3, not part of this implementation plan.
2. **Rollback mechanism:** the renderer computes inverse commands directly
   from the Change Plan at render time (not a full running-config replay).
   Surgical — only the lines that changed are touched on rollback.
3. **Validation gate:** Phase 3 is not complete until a real change has been
   applied to, and rolled back on, a real GNS3/EVE-NG lab device
   (`is_lab = true`, merged in the prior session). This is this phase's
   equivalent of the Batfish design's real-container validation task.
4. **Architecture:** a new `app/changes/` module mirroring the `app/analysis/`
   module's shape (types → driver methods → service orchestration →
   repository → schemas → API router), chosen over (a) folding change state
   into `Job.input_data`/`result_data` JSON blobs, and (b) not persisting
   plans at all and computing everything on the fly. Both alternatives were
   rejected because they weaken exactly what a change-management safety
   feature needs most: a queryable, indexed history and a persisted "this
   diff was reviewed before it was applied" record. See §4 for detail.
5. **Kill switch:** structured writes sit behind `STRUCTURED_WRITES_ENABLED`
   (off by default), gated at the router level — the same pattern already
   used for `ANALYSIS_ENABLED` and `TELNET_ENABLED`.

## 3. Scope

### In scope

- `ChangePlan` / `ChangeStep` data model and migration
- Cisco IOS/IOS-XE renderer, validator, and inverse-command computation for
  `interface_description` and `interface_admin_state`
- The full pipeline: Intent → Change Plan → Vendor Render → Validation →
  Snapshot → Diff and Risk → Explicit User Confirmation → Per-device Lock →
  Apply → Post-check → Confirm/Rollback/Assisted Recovery → Audit
  (`docs/safety-model.md` §"Future mandatory apply pipeline", now becoming
  present-tense for this one vendor and these two change types)
- Device-scoped job locking (extends the existing global
  `JobRepository.has_active` exclusivity pattern to be per-device)
- `POST /api/change-plans` (preview) and `POST /api/change-plans/{id}/apply`
  (execute), plus list/get
- A `Configure` tab on the existing `DeviceInspector`, following its existing
  tabbed structure
- `STRUCTURED_WRITES_ENABLED` kill switch, `SafetyLevel.BEST_EFFORT` ("C")
- Fixture/fake-backed automated tests, plus one opt-in real-lab-device test

### Out of scope (this slice)

- VLAN access/trunk and static route change types (later Phase 3 slices,
  same pipeline, new `ChangeType` values and renderer branches only)
- Juniper Junos / any Safety Level A or B path (Phase 6)
- Fortinet FortiOS or generic/unknown vendor writes (no vendor architecture
  work has scoped what a Fortinet renderer would even look like yet)
- AI-generated Change Plans (Phase 4 — this phase only builds the pipeline
  the AI gateway will later be restricted to producing intent for)
- Guided wizard UX polish beyond a functional preview/apply form (Phase 5)
- Bulk changes / multi-device change plans
- Confirmed-commit semantics (Junos-only, Level A)
- A hard TTL on `DRAFT` plans. A stale plan can still only apply exactly what
  it already showed the operator; post-check is the safety net if the device
  drifted in the meantime. Revisit if that proves insufficient in practice.
- Re-validating device state at apply time beyond the lock/status check
  (render-time validation is not repeated immediately before push). Noted as
  a known limitation in §8, not a silent gap.

## 4. Architecture

### 4.1 Why a dedicated module

Three approaches were considered:

**A — new `app/changes/` module with dedicated `ChangePlan`/`ChangeStep`
tables (chosen).** Mirrors `app/analysis/`: pure-logic types, driver-level
render/validate methods, a service orchestrating the pipeline, a repository,
Pydantic schemas, an API router. This is a proven shape in this exact
codebase, built and validated one phase ago.

**B — represent changes as a `JobType`, storing rendered commands and diffs
in `Job.input_data`/`result_data` JSON.** Fewer new tables, but the master
plan explicitly requires "Config history and text diff" as a first-class,
browsable feature — a JSON blob search is not that. It also thins the audit
trail for the one feature where the audit trail matters most.

**C — no persistence; compute render/diff/risk per request, apply
immediately.** Cannot support "preview now, apply later" across requests in a
multi-process deployment (API + RQ worker), and discards the persisted
"a human reviewed this exact diff before it was applied" record — the
detail that makes an audit trail meaningful for a write path.

### 4.2 Module layout

```
backend/app/changes/
  types.py       # ChangeStepIntent, RenderedChange — pure dataclasses
  risk.py        # classify_risk() — pure function, no I/O
  service.py     # ChangeService: orchestrates the full pipeline
backend/app/repositories/changes.py   # ChangeRepository
backend/app/schemas/changes.py        # Pydantic request/response views
backend/app/api/changes.py            # router, STRUCTURED_WRITES_ENABLED-gated
```

`render_change` and `validate_change` live on `DeviceDriver` itself (see
§4.3), not in `app/changes/`, because `DriverCapability.RENDER` and
`.VALIDATE` already exist as declared capability flags on the base driver —
the scaffolding already expects this to be driver-owned, vendor-specific
logic, the same way `get_interfaces()` is.

### 4.3 Driver interface changes

`app/drivers/base.py` currently declares `apply_configuration` and
`rollback` as stubs with **zero callers anywhere in the codebase** (verified
by grep) — safe to change their shape.

```python
@dataclass(frozen=True, slots=True)
class ChangeStepIntent:
    """What the operator asked for, before rendering. Mirrors ChangeStep's
    pre-render fields (change_type, target, desired_value) as a plain
    in-memory value — not yet persisted, not yet rendered."""
    change_type: ChangeType
    target: str
    desired_value: str

@dataclass(frozen=True, slots=True)
class RenderedChange:
    commands: tuple[str, ...]
    inverse_commands: tuple[str, ...]

# On DeviceDriver:
def render_change(self, step: ChangeStepIntent, current: InterfaceFacts) -> RenderedChange: ...
def validate_change(self, step: ChangeStepIntent, current: InterfaceFacts) -> list[str]: ...  # issue messages; empty = OK
def apply_configuration(self, parameters: ConnectionParameters, commands: list[str]) -> None: ...
def rollback(self, parameters: ConnectionParameters, commands: list[str]) -> None: ...  # was: rollback(parameters) -> None
```

`CiscoIOSXEDriver` currently declares its capability set **without** `APPLY`
at all (`test_cisco_driver_is_read_only_and_closes_connections` asserts
exactly this). This slice adds `RENDER, VALIDATE, APPLY, POST_CHECK,
ROLLBACK` to its capability set and implements the two interface change
types, reusing its existing `get_interfaces()` read path for current state —
no new read capability is needed. That existing test's assertion becomes
false and is updated as part of this work, not silently broken.

`DriverCapability.COMPARE` is deliberately **not** added. It names a native
candidate-vs-running compare primitive — the master plan's own vendor table
lists it as Juniper-only ("Yes") and Cisco as merely "capability-dependent."
IOS/IOS-XE has no such primitive; the "Diff and Risk" pipeline stage (§6.1)
is an application-level comparison of already-known facts, not a device
operation, so there is nothing for `COMPARE` to represent here. Revisit only
if a future Cisco capability genuinely maps to it.

Example render for `interface_description`:

```text
interface GigabitEthernet0/1
 description <desired>
```

with inverse computed from the interface's already-read current description:

```text
interface GigabitEthernet0/1
 description <previous>
```

(or `no description` if there was none). `interface_admin_state` renders
`shutdown`/`no shutdown` the same way, from the current `admin_up` fact.

### 4.4 Settings

```python
structured_writes_enabled: bool = False
```

Gated at the router level: `dependencies=[Depends(_require_enabled)]`,
identical to the pattern used for `/analysis-snapshots`.

## 5. Data model

New enums (`app/models/entities.py`):

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

`SafetyLevel` gains `BEST_EFFORT = "C"` (currently only `READ_ONLY = "D"`
exists). `A`/`B` are not added — nothing in this phase needs them. Both are
single-character values, so — unlike the two cases below — there is no
column-width concern: `ChangePlan.safety_level` is the first place
`SafetyLevel` becomes an actual mapped column, so it is sized correctly for
"D"/"C" from creation, with nothing narrower to widen.

`JobType` gains `APPLY_CHANGE = "apply_change"` (12 characters). Named
deliberately short, not `apply_change_plan` (18 characters): `jobs.type` is
an existing `VARCHAR(15)` column, already widened once in the prior phase to
fit `analyze_network` (15 characters) — the same class of bug as the
`devices.vendor` `VARCHAR(11)` issue that broke the very first migration in
this repository. `apply_change` fits inside the current column width, so
this migration does not need to touch `jobs.type` at all. Confirm this with
`alembic check` regardless — don't take the arithmetic on faith.

### `change_plans`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| device_id | UUID FK → devices, RESTRICT | |
| status | ChangePlanStatus | default `draft` |
| safety_level | SafetyLevel | `C` for this slice |
| risk | ChangeRisk | |
| pre_change_snapshot_id | UUID FK → config_snapshots, RESTRICT, nullable | set at plan creation |
| post_change_snapshot_id | UUID FK → config_snapshots, RESTRICT, nullable | set after successful apply |
| failure_code | String, nullable | typed error code on FAILED/ROLLBACK_FAILED |
| applied_at | DateTime, nullable | |
| created_at / updated_at | DateTime | `TimestampMixin` |

Reuses the **existing, immutable** `ConfigSnapshot` model from Phase 1 for
both pre- and post-change captures — no new snapshot mechanism.

### `change_steps`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| change_plan_id | UUID FK → change_plans, CASCADE | |
| change_type | ChangeType | |
| target | String | e.g. `GigabitEthernet0/1` |
| previous_value | String, nullable | sanitized before storage |
| desired_value | String | operator-supplied, already validated by the request schema |
| rendered_commands | Text | newline-joined, sanitized before storage |
| inverse_commands | Text | newline-joined, sanitized before storage |

`previous_value`, `rendered_commands`, and `inverse_commands` all
ultimately echo device-read content, so they go through `sanitize_text`
(`app.core.logging`) before storage — the same rule already applied to
Batfish findings, for the same reason.

One migration adds both tables. `alembic check` must report no drift, same
as every prior migration in this repository.

## 6. Flows

### 6.1 Preview — `POST /api/change-plans` (synchronous, no lock)

```
device_id, change_type, target, desired_value
  -> reject if device.vendor != cisco_iosxe (typed error)
  -> live-read current interface state (existing get_interfaces(), one bounded command)
  -> driver.render_change()                       [Vendor Render]
  -> driver.validate_change()                      [Validation]
     -> non-empty issues: 422, nothing persisted
  -> SnapshotService captures a fresh ConfigSnapshot [Snapshot]
  -> classify_risk()                                [Diff and Risk]
  -> persist ChangePlan(DRAFT) + ChangeStep
  -> return plan: diff, risk, safety_level, rendered commands preview
```

The returned plan is what the UI shows for **Explicit User Confirmation** —
this endpoint does not touch the device-lock at all; only `/apply` does.

### 6.2 Apply — `POST /api/change-plans/{id}/apply` (async job)

```
plan must be DRAFT, else 409
  -> enqueue JobType.APPLY_CHANGE, device-scoped exclusivity check
     [Per-device Lock: has_active(job_type, device_id=...), extended from
      the existing global-only check used by discovery/analysis]
  -> worker: mark APPLYING, commit
  -> driver.apply_configuration(rendered_commands)   [Apply]
  -> re-read interface state, compare to desired      [Post-check]
  -> success: snapshot again, mark APPLIED, applied_at = now
              [Confirm]
  -> apply raised OR post-check failed:
       driver.rollback(inverse_commands)              [Assisted Recovery]
       -> succeeds: mark ROLLED_BACK
       -> also fails: mark ROLLBACK_FAILED (manual intervention required,
                                             surfaced clearly, never hidden)
  -> audit event at every transition                  [Audit]
```

The lock is implicit: `has_active` only counts `QUEUED`/`STARTED` jobs, so
it releases the moment the job reaches any terminal state. No separate lock
table.

A plan whose device is unreachable, or whose device already has another
`APPLY_CHANGE` job running, fails immediately with **no rollback
attempt** — nothing was changed, so there is nothing to roll back. Audit
records must distinguish "never applied" from "applied then rolled back."

### 6.3 Vendor gate

Devices with `vendor != cisco_iosxe` are rejected at plan creation with a
typed `ChangeVendorUnsupportedError`, matching how the analysis pipeline
excludes non-Cisco devices from a snapshot rather than silently skipping
them.

## 7. Safety and rollback semantics

Safety Level C ("best effort") means exactly what `docs/safety-model.md`
already says: snapshot, diff, post-check, and recovery that requires
connectivity — never the word "auto-rollback." This phase does not change
that language; it makes it true for one vendor and two change types.

Rollback here is **surgical, not a full config replay**: the inverse
commands touch only the lines this specific change touched, computed once at
render time from the state actually read immediately before rendering.
Replaying an entire saved running-config was explicitly rejected (§2, decision 2) —
it risks reapplying unrelated lines that changed for other reasons between
snapshot and rollback (crypto keys, ACL ordering, anything else in flux).

`ROLLBACK_FAILED` is a legitimate, expected outcome of Level C, not a bug
class to eliminate. The UI must surface it distinctly from `FAILED` — a plan
that never touched the device needs no operator follow-up beyond retrying;
a plan stuck in `ROLLBACK_FAILED` needs a human to check the device directly.

## 8. Input validation, error handling, and limits

### 8.1 Input validation

- `target` must name an interface that exists on the device's last-read
  interface list (checked against the live read done during preview, not a
  possibly-stale cached value)
- `desired_value` for `interface_description`: non-empty, ≤ 240 characters
  (Cisco IOS/IOS-XE limit)
- `desired_value` for `interface_admin_state`: literal `up` or `down`

### 8.2 Error handling

| Condition | Result |
|---|---|
| `STRUCTURED_WRITES_ENABLED` is false | 403 `structured_writes_disabled_by_policy` |
| Device vendor is not Cisco IOS/IOS-XE | 422 `change_vendor_unsupported` |
| `validate_change` reports issues | 422, plan not persisted |
| Device unreachable during preview | 503, plan not persisted |
| `/apply` called on a non-`DRAFT` plan | 409 `change_plan_not_draft` |
| Another `APPLY_CHANGE` job is active for this device | 409 `change_plan_device_locked` |
| Apply fails before any command reaches the device | plan → `FAILED`, no rollback attempted |
| Apply fails partway, or post-check fails | plan → `ROLLED_BACK` or `ROLLBACK_FAILED` |

### 8.3 Known limitation: no re-validation immediately before push

Validation runs once, at preview time. If the device's interface state
drifts between preview and apply (another session changes it, or a routing
protocol brings a link down), apply proceeds against the plan as rendered.
Post-check is the safety net that catches a resulting state mismatch, but it
cannot prevent the push itself. This is a deliberate scope cut for the first
slice, not an oversight — revisit if it proves insufficient once VLAN and
static route slices land, or before any multi-operator deployment.

## 9. Testing

- Pure logic (`render_change`, `validate_change`, `classify_risk`) gets
  ordinary unit tests — no I/O, no fixtures needed beyond plain data
- Full preview → apply → post-check flow tested against the existing
  `FakeTransportFactory`, including a forced-failure case proving rollback
  actually triggers, and a forced-rollback-failure case proving
  `ROLLBACK_FAILED` is reachable and distinct from `FAILED`
- Device-scoped locking: two applies to the *same* device conflict, two
  applies to *different* devices do not — modeled on the existing
  `test_only_one_analysis_may_be_active` test
- Migration: upgrade/downgrade plus `alembic check` against real
  PostgreSQL, same as every prior migration
- `test_cisco_driver_is_read_only_and_closes_connections` is updated: it no
  longer asserts `APPLY` is absent from Cisco's capability set once this
  slice implements it
- Frontend: Vitest component tests for the new `Configure` tab, following
  the existing fixture/mock-API pattern used by `AnalysisPage`'s tests
- **Required before this phase is considered done:** one opt-in test, gated
  by an env var (`RUN_LAB_TESTS`-style), that applies a real
  `interface_description` change to a real GNS3/EVE-NG lab device
  (`is_lab = true`), confirms it landed, then forces and confirms a real
  rollback. This is the evidence that the pipeline works against an actual
  device, not just fixtures — the equivalent of the Batfish plan's Task 9,
  and the reason lab-device support was merged in the prior session.

## 10. Success criteria

1. An operator can preview an interface description or admin-state change
   for a Cisco IOS/IOS-XE device, see the diff, risk, and rendered CLI
   commands, and explicitly apply it.
2. A successful apply is verified by post-check and produces a post-change
   snapshot; the plan is marked `APPLIED`.
3. A forced failure (fixture-driven) triggers rollback, and the plan lands
   in `ROLLED_BACK`. A forced rollback failure lands in `ROLLBACK_FAILED`
   and is visibly distinct in the UI.
4. Two concurrent apply attempts against the same device conflict; concurrent
   attempts against different devices do not.
5. `STRUCTURED_WRITES_ENABLED=false` (the default) makes every endpoint in
   this router fail closed with 403, and no existing capability is affected.
6. `alembic check` reports no drift after the new migration, on real
   PostgreSQL, both directions.
7. A real change was applied to, and rolled back on, a real GNS3/EVE-NG lab
   device, and the outcome is recorded in `docs/IMPLEMENTATION_STATUS.md`
   the same honest way the Batfish real-container validation was recorded —
   what was reached, not what is merely enforced-but-untested.

## 11. Follow-on work

- VLAN access/trunk and static route change types, same pipeline, new
  `ChangeType` values and Cisco renderer branches (later Phase 3 slices)
- Re-validation immediately before push, if drift between preview and apply
  proves to matter in practice (§8.3)
- A "stale plan" warning in the UI if a `DRAFT` plan is old, without a hard
  TTL (§3, out of scope)
- Juniper Junos / Safety Level A, B (Phase 6)
- AI-generated Change Plan intent (Phase 4) — this phase's pipeline is the
  thing AI-generated intent will later be restricted to producing input for,
  never allowed to call `/apply` directly
