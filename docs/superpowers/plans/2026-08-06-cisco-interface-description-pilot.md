# Cisco Interface Description Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one Safety Level C structured-write path that sets or clears a Cisco interface description through immutable preview, explicit confirmation, bounded apply, post-check, and assisted rollback.

**Architecture:** A preview captures an immutable running-config snapshot, renders only the interface-description grammar, encrypts command payloads, and stores an immutable `ChangePlan`. Apply consumes a plan/device-scoped one-time Maintenance Code, acquires a Redis device lock, rejects stale state, executes one bounded Scrapli configuration session, and stores outcome in a separate `ChangeExecution`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, Redis, RQ, Scrapli, AES-GCM, React 19, TanStack Query, Pytest, Vitest.

## Global Constraints

- This plan starts only after the Phase 1-2 readiness and local-provider exit gates pass.
- Only `interface_description` is accepted. There is no raw command, admin-state, VLAN, trunk, SVI, route, bulk, or AI input.
- The selected interface must be an existing observed `Interface` row for the exact registered Cisco device.
- Description is a bounded printable single line; control characters and line separators are rejected.
- Apply changes running-config only. Never send `write memory`, `copy running-config startup-config`, or an equivalent save command.
- Every apply requires immutable snapshot, diff/risk, exact device name, fresh one-time Maintenance Code, device lock, stale check, and post-check.
- A preview plan expires after 30 minutes; a Maintenance Code expires after exactly 15 minutes and cannot outlive its plan.
- Safety Level C means best effort. Never label or implement automatic rollback.
- Assisted rollback is a new preview and requires a new typed device name and Maintenance Code.
- Unknown/changed host key, unsupported platform, timeout, disconnect, failed privilege, failed response, stale state, or indeterminate post-check fails closed.
- Commands, raw config, credentials, Maintenance Codes/hashes, raw exceptions, and terminal content never enter logs, events, API errors, or Git fixtures.
- Routine tests are network-free. Write-lab validation has a second explicit opt-in and runs virtual Cisco before physical Cisco.
- No startup-config persistence, new network dependency, generalized change DSL, scheduler, or automatic retry.
- Do not change `docs/network-automation-final-plan.md`.

---

## File Structure

- `backend/app/models/entities.py`: immutable `ChangePlan`, mutable `ChangeExecution`, Level C, and job/status enums.
- `backend/app/services/change_plans.py`: preview, immutable plan encryption, diff/risk, expiry, and assisted rollback preview.
- `backend/app/services/maintenance_codes.py`: one-time Redis code issue/atomic consume.
- `backend/app/services/device_write_lock.py`: token-owned bounded device lock.
- `backend/app/services/change_execution.py`: apply orchestration and sanitized state transitions.
- `backend/app/drivers/cisco_changes.py`: interface-description validation/render/parsing only.
- `backend/app/drivers/transport.py`: bounded `send_configs` support through Scrapli.
- `backend/app/api/change_plans.py`, `change_executions.py`: authenticated preview/code/apply/rollback contracts.
- `frontend/src/features/changes/InterfaceDescriptionChange.tsx`: preview and confirmation workflow.
- `backend/tests/lab/test_cisco_interface_description_lab.py`: separately opted-in restore-to-original acceptance.

### Task 1: Add immutable plan and separate execution records

**Files:**
- Create: `backend/app/schemas/change_plans.py`
- Create: `backend/app/schemas/change_executions.py`
- Create: `backend/app/repositories/change_plans.py`
- Create: `backend/app/repositories/change_executions.py`
- Create: `backend/migrations/versions/20260806_0007_change_plans.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/core/errors.py`
- Test: `backend/tests/integration/test_change_plan_models.py`
- Test: `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Consumes: existing `Device`, `Interface`, `ConfigSnapshot`, `EnvelopeCipher`, timestamp/UUID helpers.
- Produces: immutable `ChangePlan`, stateful `ChangeExecution`, `ChangeType.INTERFACE_DESCRIPTION`, `SafetyLevel.BEST_EFFORT` (`"C"`).

- [ ] **Step 1: Write failing model invariant tests**

```python
def test_change_plan_cannot_be_updated_or_deleted(session, change_plan):
    change_plan.risk_summary = {"changed": True}
    with pytest.raises(ChangePlanImmutableError):
        session.flush()
    session.rollback()
    session.delete(change_plan)
    with pytest.raises(ChangePlanImmutableError):
        session.flush()


def test_execution_status_changes_without_mutating_plan(session, change_plan):
    execution = ChangeExecution(plan_id=change_plan.id, status=ChangeExecutionStatus.APPLYING)
    session.add(execution)
    session.flush()
    execution.status = ChangeExecutionStatus.SUCCEEDED
    session.flush()
    assert change_plan.change_type is ChangeType.INTERFACE_DESCRIPTION
```

Migration tests assert foreign keys, plan expiry, one execution-to-plan relation, encrypted payload column, the `device_capabilities.safety_level IN ('C', 'D')` constraint, and database update/delete triggers for `change_plans`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/integration/test_change_plan_models.py tests/integration/test_migrations.py -q`

Expected: FAIL because the entities and migration do not exist.

- [ ] **Step 3: Add exact enums and records**

```python
class SafetyLevel(StrEnum):
    BEST_EFFORT = "C"
    READ_ONLY = "D"

class ChangeType(StrEnum):
    INTERFACE_DESCRIPTION = "interface_description"

class ChangeExecutionStatus(StrEnum):
    PENDING_CONFIRMATION = "pending_confirmation"
    APPLYING = "applying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    ROLLBACK_READY = "rollback_ready"
    ROLLED_BACK = "rolled_back"
```

`ChangePlan` fields: device/interface/snapshot IDs, snapshot SHA-256, change type, desired description plus `clear_description`, current description, encrypted payload, sanitized diff/risk JSON, renderer policy version, optional `rollback_of_plan_id`, created timestamp, and expiry exactly 30 minutes later. `ChangeExecution` fields: plan/job IDs, status, maintenance-window ID, sanitized result/error code, created/started/finished timestamps.

- [ ] **Step 4: Enforce immutability in ORM and PostgreSQL**

Copy the existing snapshot ORM listeners and migration trigger pattern for `change_plans`. Execution updates remain allowed through repository transition methods only.

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command. Expected: PASS.

```powershell
git add backend/app backend/migrations/versions/20260806_0007_change_plans.py backend/tests
git commit -m "feat: add immutable change plans"
```

### Task 2: Render and execute only Cisco interface-description commands

**Files:**
- Create: `backend/app/drivers/cisco_changes.py`
- Modify: `backend/app/drivers/base.py`
- Modify: `backend/app/drivers/cisco_iosxe.py`
- Modify: `backend/app/drivers/transport.py`
- Modify: `backend/tests/fakes.py`
- Create: `backend/tests/unit/test_cisco_changes.py`
- Modify: `backend/tests/unit/test_drivers.py`

**Interfaces:**
- Consumes: an observed interface name, current description, and desired description/clear flag.
- Produces: `RenderedInterfaceDescription(apply_commands, rollback_commands, current, desired)`, strict renderer validation, and `CiscoIOSXEDriver.apply_interface_description(parameters, rendered, expected_sha256) -> InterfaceDescriptionApplyResult`.

- [ ] **Step 1: Write failing renderer golden tests**

```python
@pytest.mark.parametrize(("desired", "expected"), [
    ("Lab uplink", ("interface GigabitEthernet1/0/1", "description Lab uplink")),
    (None, ("interface GigabitEthernet1/0/1", "no description")),
])
def test_renderer_emits_only_the_pilot_grammar(desired, expected):
    rendered = render_interface_description("GigabitEthernet1/0/1", "Old", desired)
    assert rendered.apply_commands == expected


@pytest.mark.parametrize("value", ["bad\nshutdown", "bad\rtext", "bad\x00text", "x" * 241])
def test_renderer_rejects_multiline_control_and_oversized_text(value):
    with pytest.raises(InvalidChangeIntentError):
        render_interface_description("GigabitEthernet1/0/1", None, value)
```

Add invalid interface grammar, unchanged intent, clear-with-text, forbidden command token, Scrapli response failure, privilege failure, cleanup, and assert no save command appears.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_cisco_changes.py tests/unit/test_drivers.py -q`

Expected: FAIL because renderer/config transport methods do not exist.

- [ ] **Step 3: Implement bounded renderer and parser**

```python
_INTERFACE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9./:-]{0,127}$")
_DESCRIPTION = re.compile(r"^[ -~]{1,240}$")

def render_interface_description(interface: str, current: str | None, desired: str | None) -> RenderedInterfaceDescription:
    if not _INTERFACE_NAME.fullmatch(interface): raise InvalidChangeIntentError()
    if desired is not None and not _DESCRIPTION.fullmatch(desired): raise InvalidChangeIntentError()
    if desired == current: raise ChangeHasNoEffectError()
    apply = (f"interface {interface}", f"description {desired}" if desired is not None else "no description")
    rollback = (f"interface {interface}", f"description {current}" if current is not None else "no description")
    validate_interface_description_commands(apply)
    validate_interface_description_commands(rollback)
    return RenderedInterfaceDescription(apply, rollback, current, desired)
```

Add a parser that reads the exact interface stanza from normalized running config and returns only its description. It rejects duplicate/ambiguous stanzas.

- [ ] **Step 4: Extend capability metadata without weakening generic devices**

Add `write_safety_level: SafetyLevel | None = None` to `DriverCapabilitySet`. Reject write capabilities when it is absent. `records()` reports Level C only for supported write capabilities and Level D for reads/unsupported capabilities. Cisco declares render/validate/compare/apply/post-check/rollback at Level C; Generic remains Level D.

- [ ] **Step 5: Add Scrapli configuration transport**

Extend `NetworkTransport` with `send_configs(commands: Sequence[str]) -> None`. Cisco Scrapli calls `send_configs(list(commands))` and rejects if aggregate or any response failed. Generic transport raises `UnsupportedCapabilityError`. Keep the existing pinned known-hosts temp-file and idempotent close ownership.

- [ ] **Step 6: Apply and post-check in one pinned session**

`CiscoIOSXEDriver.apply_interface_description()` opens one session, reads running config, compares SHA-256 with expected preview hash, sends the two commands, reads the exact interface stanza, and returns observed description. Any response uncertainty maps to a fixed sanitized driver error. It never calls a save method.

- [ ] **Step 7: Run tests and commit**

Run the Step 2 command. Expected: PASS.

```powershell
git add backend/app/drivers backend/tests/unit backend/tests/fakes.py
git commit -m "feat: render Cisco interface descriptions"
```

### Task 3: Build immutable Preview with snapshot, diff, risk, and encrypted commands

**Files:**
- Create: `backend/app/services/change_plans.py`
- Create: `backend/app/api/change_plans.py`
- Modify: `backend/app/services/snapshots.py`
- Modify: `backend/app/container.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/unit/test_change_plans.py`
- Test: `backend/tests/integration/test_change_plan_vertical_slice.py`

**Interfaces:**
- Consumes: Task 1 entities, Task 2 renderer, `SnapshotService`, pinned `DeviceService`, existing interface inventory.
- Produces: `ChangePlanService.preview(request) -> ChangePlan`, `preview_assisted_rollback(plan_id) -> ChangePlan`, and secret-free `ChangePlanView`.

- [ ] **Step 1: Write failing preview tests**

```python
def test_preview_captures_snapshot_and_returns_only_bounded_diff(change_plan_service):
    plan = change_plan_service.preview(interface_description_request())
    assert plan.snapshot.sha256 == sha256(FIXTURE_RUNNING_CONFIG.encode()).hexdigest()
    assert plan.diff == {"interface": "GigabitEthernet1/0/1", "before": "Old", "after": "Lab uplink"}
    assert "show running-config" not in plan.model_dump_json()
    assert "interface GigabitEthernet" not in event_payloads()


def test_preview_rejects_stale_or_foreign_interface(change_plan_service):
    with pytest.raises(InvalidChangeIntentError):
        change_plan_service.preview(request_for_interface_on_another_device())
```

Add non-Cisco, missing pin, unavailable Level C capability, empty config, plan expiry, encrypted payload tamper, and assisted rollback linking tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_change_plans.py tests/integration/test_change_plan_vertical_slice.py -q`

Expected: FAIL because preview service/API do not exist.

- [ ] **Step 3: Share snapshot capture without exposing raw config**

Add internal:

```python
@dataclass(frozen=True, slots=True)
class CapturedSnapshot:
    snapshot: ConfigSnapshot
    plaintext: str

def capture_for_plan(self, device_id: UUID) -> CapturedSnapshot:
    snapshot, plaintext = self._capture(device_id, job_id=None)
    return CapturedSnapshot(snapshot=snapshot, plaintext=plaintext)
```

The existing public capture behavior remains metadata-only. Preview holds plaintext in local variables only, parses the interface description, encrypts snapshot through the existing store, then clears references. It never serializes plaintext into plan, job, event, or API data.

- [ ] **Step 4: Encrypt rendered payload with plan-scoped AAD**

Use `EnvelopeCipher(container.key_provider, purpose="change-plan-payloads")` and AAD `change-plan:v1:<plan_id>:<device_id>`. JSON contains version 1 plus apply/rollback command arrays only. `ChangePlanView` omits ciphertext and returns sanitized diff, risk `{safety_level: "C", automatic_rollback: false, persists_to_startup: false}`, snapshot ID/hash/time, target, renderer version, and expiry.

- [ ] **Step 5: Implement authenticated preview APIs**

- `POST /api/change-plans` accepts only `{device_id, interface_id, change_type: "interface_description", desired_description, clear_description}`.
- `POST /api/change-plans/{id}/assisted-rollback-preview` creates a new immutable plan from fresh current state and the original before value.
- `GET /api/change-plans/{id}` returns the secret-free view.

No raw-command field exists in any schema.

- [ ] **Step 6: Run tests and commit**

Run the Step 2 command. Expected: PASS.

```powershell
git add backend/app backend/tests
git commit -m "feat: preview interface description changes"
```

### Task 4: Add one-time Maintenance Codes and exclusive device write locks

**Files:**
- Create: `backend/app/services/maintenance_codes.py`
- Create: `backend/app/services/device_write_lock.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/container.py`
- Modify: `backend/app/api/change_plans.py`
- Test: `backend/tests/unit/test_maintenance_codes.py`
- Test: `backend/tests/unit/test_device_write_lock.py`

**Interfaces:**
- Consumes: Redis, `MasterKeyProvider.derive_key()`, immutable plan/device IDs.
- Produces: `MaintenanceCodeStore.issue(plan_id, device_id, actor) -> IssuedMaintenanceCode`, atomic `consume(plan_id, device_id, actor, code) -> maintenance_window_id`, and token-owned `RedisDeviceWriteLock`.

- [ ] **Step 1: Write failing code and lock tests**

```python
def test_code_is_plan_device_scoped_single_use_and_15_minutes(store):
    issued = store.issue(PLAN_ID, DEVICE_ID, "local-admin")
    assert issued.expires_at - issued.created_at == timedelta(minutes=15)
    assert store.consume(PLAN_ID, DEVICE_ID, "local-admin", issued.code) == issued.window_id
    with pytest.raises(MaintenanceCodeConsumedError):
        store.consume(PLAN_ID, DEVICE_ID, "local-admin", issued.code)


def test_only_lock_owner_can_release_and_release_is_idempotent(lock_store):
    lease = lock_store.acquire(DEVICE_ID, EXECUTION_ID)
    with pytest.raises(DeviceWriteLockedError):
        lock_store.acquire(DEVICE_ID, OTHER_EXECUTION_ID)
    lock_store.release(lease)
    lock_store.release(lease)
```

Also test expired/wrong plan/wrong device/wrong actor/wrong code, atomic concurrent consume, Redis unavailable, lease expiry, cancellation cleanup, and no plaintext code/hash in logs/events/errors.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_maintenance_codes.py tests/unit/test_device_write_lock.py -q`

Expected: FAIL because stores do not exist.

- [ ] **Step 3: Implement code issue and atomic consume**

Generate a 10-character unambiguous code with `secrets`. Derive `maintenance-code-hmac` from the master key and store only HMAC plus plan/device/actor/expiry/unused state. Use one Redis Lua script to compare all fields and mark consumed atomically. Set TTL to exactly 900 seconds. Return plaintext only once from `POST /api/change-plans/{id}/maintenance-window`.

- [ ] **Step 4: Implement bounded token-owned lock**

Use `SET key token NX EX <ttl>` for acquire and a compare-and-delete Lua script for release. Add settings `structured_write_job_timeout_seconds=180` and `device_write_lock_ttl_seconds=240`; validate lock TTL is at least job timeout plus 30 seconds. No read or terminal lock behavior changes.

- [ ] **Step 5: Run tests and commit**

Run the Step 2 command plus `tests/unit/test_config.py`. Expected: PASS.

```powershell
git add backend/app backend/tests
git commit -m "feat: gate writes with one-time maintenance codes"
```

### Task 5: Execute, post-check, and produce Assisted Rollback without auto-recovery

**Files:**
- Create: `backend/app/services/change_execution.py`
- Create: `backend/app/api/change_executions.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/jobs/tasks.py`
- Modify: `backend/app/jobs/queue.py`
- Modify: `backend/app/services/jobs.py`
- Modify: `backend/app/repositories/jobs.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/schemas/jobs.py`
- Test: `backend/tests/unit/test_change_execution.py`
- Test: `backend/tests/integration/test_change_execution_vertical_slice.py`
- Test: `backend/tests/unit/test_queue.py`

**Interfaces:**
- Consumes: encrypted plan, Maintenance Code consume, device lock, pinned credentials, Cisco driver apply/post-check.
- Produces: `ChangeExecutionService.request_apply(plan_id, device_name_confirmation, maintenance_code, actor) -> ChangeExecution`, RQ execution, fixed result states, and rollback-ready linkage.

- [ ] **Step 1: Write failing end-to-end fake transport tests**

```python
def test_apply_rechecks_snapshot_sends_no_save_and_requires_exact_postcheck(client, fake_transport):
    execution = request_apply(client, typed_name="Core-SW", code=VALID_CODE)
    run_job(execution.job_id)
    assert fake_transport.config_batches == [("interface GigabitEthernet1/0/1", "description Lab uplink")]
    assert all("write" not in command and "copy" not in command for batch in fake_transport.config_batches for command in batch)
    assert get_execution(client, execution.id)["status"] == "succeeded"


def test_postcheck_failure_is_rollback_ready_and_never_auto_applies(client, fake_transport):
    fake_transport.postcheck_description = "Unexpected"
    execution = apply_ready_plan(client)
    run_job(execution.job_id)
    body = get_execution(client, execution.id)
    assert body["status"] == "rollback_ready"
    assert fake_transport.config_batches == [APPLY_BATCH]
```

Add exact-name mismatch, expired/stale plan, consumed code, lock conflict, stale hash, privilege rejection, disconnect before/after config, partial/unknown response, timeout, cleanup, fresh rollback confirmation/code, and audit/log secrecy tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_change_execution.py tests/integration/test_change_execution_vertical_slice.py tests/unit/test_queue.py -q`

Expected: FAIL because execution service and job types do not exist.

- [ ] **Step 3: Validate and enqueue without carrying secrets**

`POST /api/change-executions` accepts `{plan_id, device_name_confirmation, maintenance_code}`. Validate exact stored device name, consume code, create execution/job, and enqueue only execution UUID. The job input/result contains IDs and sanitized codes only.

- [ ] **Step 4: Execute in this exact order**

1. Lock execution row and ensure `pending_confirmation`.
2. Reject expired plan before device access.
3. Acquire device write lock.
4. Decrypt plan payload and load pinned device credentials.
5. Open one pinned Cisco session.
6. Re-read running config and compare full normalized SHA-256 to preview hash.
7. Send the exact two-command batch once.
8. Read exact resulting interface description.
9. Mark success only on exact desired value.
10. Clear command/credential references and release transport/lock idempotently.

Map known no-apply failures to `failed`; any response/disconnect where application is uncertain becomes `partial` or `unknown`; known prior state plus failed post-check becomes `rollback_ready`. Never call rollback automatically.

- [ ] **Step 5: Route worker failures without raw exceptions**

Add `JobType.APPLY_CHANGE` and `JobType.APPLY_ROLLBACK`. Update RQ timeout to use the 180-second structured-write setting for these types and retain existing read defaults. Events allow only execution/plan/device IDs, change type, safety level, policy version, phase, result code, and rollback availability.

- [ ] **Step 6: Require a fresh rollback preview and gate**

The rollback button first calls Task 3's assisted rollback preview. That new plan uses current state/snapshot and desired original description, then repeats a new name confirmation, new Maintenance Code, lock, stale check, apply, and post-check. Successful rollback marks the original execution `rolled_back` only after the rollback execution succeeds.

- [ ] **Step 7: Run tests and commit**

Run the Step 2 command. Expected: PASS with fake transports only.

```powershell
git add backend/app backend/tests
git commit -m "feat: execute bounded Cisco description changes"
```

### Task 6: Add Preview, confirmation, result, and recovery UI

**Files:**
- Create: `frontend/src/features/changes/InterfaceDescriptionChange.tsx`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/network.ts`
- Modify: `frontend/src/features/inventory/DeviceInspector.tsx`
- Modify: `frontend/src/styles.css`
- Create: `frontend/tests/interface-description-change.test.tsx`
- Modify: `frontend/tests/device-inspector.test.tsx`

**Interfaces:**
- Consumes: change-plan/maintenance-window/execution APIs from Tasks 3-5.
- Produces: interface-description wizard with no raw-command entry and explicit Level C/running-only/recovery states.

- [ ] **Step 1: Write failing UI workflow tests**

```tsx
it('shows snapshot diff and requires exact name plus maintenance code before apply', async () => {
  renderChangeFlow();
  await previewDescription('Lab uplink');
  expect(screen.getByText(/Safety Level C/i)).toBeVisible();
  expect(screen.getByText(/running-config only/i)).toBeVisible();
  expect(screen.getByText(/Old/)).toBeVisible();
  expect(screen.getByText(/Lab uplink/)).toBeVisible();
  expect(screen.getByRole('button', { name: /^apply$/i })).toBeDisabled();
  await user.type(screen.getByLabelText(/type device name/i), 'Core-SW');
  await user.type(screen.getByLabelText(/maintenance code/i), 'ABCDE-FGHIJ');
  expect(screen.getByRole('button', { name: /^apply$/i })).toBeEnabled();
});

it('offers assisted rollback but never automatic rollback', async () => {
  renderExecution({ status: 'rollback_ready' });
  expect(screen.getByRole('button', { name: /preview assisted rollback/i })).toBeVisible();
  expect(screen.queryByText(/automatic rollback/i)).not.toBeInTheDocument();
});
```

Add clear description, expired code/plan, stale plan, lock conflict, partial/unknown, non-retryable disabled Apply, focus-to-error, and no raw config/command field tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location frontend; npm.cmd test -- --run tests/interface-description-change.test.tsx tests/device-inspector.test.tsx`

Expected: FAIL because the change UI does not exist.

- [ ] **Step 3: Add the smallest bounded change form**

Place `Change description` beside an observed interface only when the device is Cisco and the interface-description pipeline is Level C. Use one text input plus explicit Clear checkbox; changing intent invalidates the old preview. No textarea or raw command preview is accepted from the user.

- [ ] **Step 4: Render the complete confirmation panel**

Show device/interface, before/after, snapshot time and hash reference, sanitized two-line diff, Safety Level C, no-auto-rollback warning, running-config-only warning, plan/code expiry, lock/stale status, exact device-name field, and Maintenance Code field. The generated code is displayed once; refresh requires issuing another window.

- [ ] **Step 5: Render execution and recovery states**

Poll the existing job/execution endpoints only while the panel is mounted. `partial`, `unknown`, and `rollback_ready` use `role="alert"`, disable Apply, and show fixed guidance. Assisted rollback always starts a fresh preview screen.

- [ ] **Step 6: Run tests and commit**

Run the Step 2 command, `npm.cmd run typecheck`, and `npm.cmd run lint`. Expected: PASS.

```powershell
git add frontend/src frontend/tests
git commit -m "feat: add interface description change UI"
```

### Task 7: Verify, document, and gate virtual then physical write validation

**Files:**
- Create: `backend/tests/lab/test_cisco_interface_description_lab.py`
- Modify: `docs/lab-test-guide.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/safety-model.md`
- Test: complete backend/frontend/Compose verification

**Interfaces:**
- Consumes: complete pilot and existing read-only lab harness rules.
- Produces: separately opted-in write harness and conservative metadata-only status.

- [ ] **Step 1: Write the skipped-by-default harness contract test**

```python
@pytest.mark.lab
def test_interface_description_round_trip_requires_write_opt_in():
    require_exact_env("RUN_WRITE_LAB_TESTS", "1")
    require_exact_env("LAB_EXPECTED_PLATFORM", "cisco_iosxe")
    require_exact_target("LAB_DEVICE_HOST")
    require_exact_interface("LAB_WRITE_INTERFACE")
    require_nonempty("LAB_KNOWN_HOSTS_FILE")
    require_exact_env("LAB_WRITE_RECOVERY_CONFIRMED", "1")
    # Preview/apply/post-check/assisted rollback/restore through product services.
```

The ordinary `RUN_LAB_TESTS=1` flag must not authorize this test. Require exact target, dedicated interface, verified pin, original description, console/OOB owner, immutable snapshot, reviewed preview, and no-save acknowledgment. Stop on any unexpected behavior.

- [ ] **Step 2: Prove routine discovery skips all network access**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/lab/test_cisco_interface_description_lab.py -q`

Expected: SKIPPED before any socket or credential access.

- [ ] **Step 3: Run complete automated verification**

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m ruff check --no-cache .
.\.venv\Scripts\pyright.exe
.\.venv\Scripts\python.exe -m pytest
Set-Location ..\frontend
npm.cmd run verify
Set-Location ..
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.dev.yml config --quiet
```

Expected: all PASS; both read and write lab suites remain skipped.

- [ ] **Step 4: Record automated status conservatively**

Mark only Cisco interface-description render/validate/preview/apply/post-check/assisted rollback as implemented. VLAN/admin-state/trunk/SVI/route/bulk/AI/startup-save remain Not Implemented. Use `Automated verification passed; hardware validation pending.`

- [ ] **Step 5: Run authorized virtual write validation first, only with fresh approval**

Use one dedicated virtual Cisco interface. Verify preview, snapshot, apply, exact post-check, fresh assisted rollback, and original running description restoration. Confirm startup configuration was not saved. Record metadata and pass/fail only.

- [ ] **Step 6: Run authorized physical validation second, only with fresh approval**

Use the exact separately approved physical target/window and working OOB recovery. Stop on drift, unexpected prompt/privilege/output/disconnect. Do not infer authorization from this plan or from a previous read-only run.

- [ ] **Step 7: Detect change scope and commit**

```powershell
node .gitnexus/run.cjs detect-changes -r "C:\Users\User\Desktop\Coding\Terraformer" --scope compare --base-ref main
git add backend/tests/lab/test_cisco_interface_description_lab.py docs/lab-test-guide.md docs/IMPLEMENTATION_STATUS.md docs/CAPABILITY_MATRIX.md docs/safety-model.md
git commit -m "docs: gate interface description validation"
```

Expected: scope is limited to interface-description change planning/execution, UI, tests, and documentation; no emulator mutation or other structured-write path appears.
