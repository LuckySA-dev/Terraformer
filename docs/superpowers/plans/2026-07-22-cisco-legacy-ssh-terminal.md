# Cisco Legacy SSH Compatibility and Device Terminal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit, per-device Cisco legacy SSH compatibility to every SSH connection boundary and make the existing device terminal secure, diagnosable, and usable without weakening modern defaults or changing USB Direct Mode.

**Architecture:** Persist one compatibility enum on each device and translate it through one pure, versioned policy module into request-scoped OpenSSH and AsyncSSH options. Admit every structured or terminal connection through one Redis-backed gate, keep secrets just-in-time at the transport boundary, map failures to a fixed sanitized catalog, and retain separate Scrapli and AsyncSSH transports. Extend the existing shared terminal/session UI only for safe error metadata, paste confirmation, and lifecycle behavior; apply width changes only while the device Terminal tab is active.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, Redis 6, RQ, Scrapli 2025.1.30 with system OpenSSH, AsyncSSH 2.23.1, React 19, TypeScript 5.9, xterm 6, Vitest, pytest, Ruff, Pyright, Docker Compose

## Global Constraints

- Do not contact, scan, authenticate to, or configure a real device while implementing or running routine tests.
- Leave `docs/network-automation-final-plan.md` unchanged and preserve all structured writes as Not Implemented / Safety Level D.
- Legacy algorithms are exact, additive, request-scoped, and opt-in. Never implement automatic fallback or change global SSH defaults.
- Never place credentials in Redis keys, queue payloads, subprocess arguments, environment variables, temporary files, URLs, WebSocket messages, audit details, logs, fixtures, or persisted job failures.
- Never retain terminal input/output, raw exceptions, or peer algorithm lists. Redis keys must contain only digested endpoints, and audit/error/log records must omit addresses and hostnames; the in-memory connection parameters and OpenSSH destination argument remain the necessary target boundary.
- Preserve mandatory host-key behavior from `SSH_STRICT_HOST_KEY`; compatibility mode must not alter it.
- Treat `TerminalSession` as HIGH-risk shared code. Before editing it, report the GitNexus blast radius, then run both SSH terminal and all USB Direct Mode regressions.
- Before editing any existing symbol, run GitNexus `impact({target: "<symbol>", direction: "upstream"})`. Stop and warn the user before proceeding if the result is HIGH or CRITICAL.
- Before every task commit, run GitNexus `detect_changes({scope: "compare", base_ref: "main"})` and confirm only the task's expected symbols and flows changed.
- Preserve unrelated dirty-worktree files, especially `AGENTS.md`, `.claude/`, `CLAUDE.md`, and `skills-lock.json`.

## File Map

### Backend domain and policy

- Create `backend/app/drivers/ssh_compatibility.py`: immutable policy version, exact allowed algorithm tuples, OpenSSH option builder, AsyncSSH keyword builder, and kill-switch validation.
- Create `backend/app/drivers/ssh_errors.py`: fixed sanitized connection-phase catalog and typed transport-error translation.
- Create `backend/migrations/versions/20260722_0003_legacy_ssh.py`: add non-null `ssh_compatibility` with `modern` migration default.
- Modify `backend/app/models/entities.py` and `backend/app/models/__init__.py`: define/export `SSHCompatibility` and persist it on `Device`.
- Modify `backend/app/schemas/devices.py`: carry compatibility and ephemeral Group1 acknowledgment through create, update, and connection-test requests; return compatibility in `DeviceView`.
- Modify `backend/app/drivers/base.py`: carry normalized compatibility in `ConnectionParameters`.
- Modify `backend/app/core/config.py`, `.env.example`, and `deploy/compose.yml`: add three SSH policy switches and explicit connection/session limits; cap Uvicorn WebSocket frames at 8 KiB.

### Backend admission and connection paths

- Create `backend/app/services/connection_gate.py`: Redis-backed rate, cooldown, concurrency, TTL-permit, and release contract using digested target keys.
- Modify `backend/app/container.py`: inject and expose the shared gate; remove the process-local terminal-only counter.
- Modify `backend/app/drivers/transport.py`: apply password-only OpenSSH and exact compatibility options via Scrapli `transport_options["open_cmd"]`.
- Modify `backend/app/drivers/generic_readonly.py` and `backend/app/drivers/cisco_iosxe.py`: use the sanitized SSH error translator without raw exception chains.
- Modify `backend/app/services/devices.py`: validate policy, perform fresh create/update tests, admit every synchronous connection, account for authentication results, and release credentials/permits.
- Modify `backend/app/services/snapshots.py`: use the same admitted connection scope for snapshot reads.
- Modify `backend/app/api/devices.py` and `backend/app/api/discovery.py`: inject the shared gate and preserve backend-side retesting for direct add and discovery approval.
- Modify `backend/app/jobs/tasks.py`: preserve opaque queue payloads and sanitized worker failures while using the gated device service.
- Modify `backend/app/api/terminal.py`: use the saved compatibility policy, Group1 acknowledgment, Redis gate, AsyncSSH password-only options, phase-specific errors, PTY/shell timeout, maximum duration, and idempotent cleanup.

### Frontend device and terminal paths

- Modify `frontend/src/types/api.ts` and `frontend/src/api/network.ts`: add compatibility input/output and typed sanitized connection-error details.
- Modify `frontend/src/features/inventory/DeviceForm.tsx`: add mode selection, warnings, Group1 acknowledgment, and connection-test fingerprint invalidation.
- Modify `frontend/src/features/inventory/InventoryPage.tsx`: show a Legacy badge without changing discovery behavior.
- Modify `frontend/src/features/inventory/DeviceInspector.tsx`: pass device compatibility into the terminal, show the badge, and apply a Terminal-tab-only modifier.
- Modify `frontend/src/features/inventory/TerminalPanel.tsx`: send Group1 acknowledgment, expose accessible tabs, pass active state, and request SSH paste confirmation.
- Modify `frontend/src/features/terminal/transport.ts` and `frontend/src/features/terminal/SshWebSocketTransport.ts`: carry `phase`, `retryable`, and fixed `recommendedAction`; never carry raw errors.
- Modify `frontend/src/features/terminal/inputPolicy.ts`: normalize multiline detection, detect large/unsafe pastes, and enforce the 4 KiB pending-input bound.
- Modify `frontend/src/features/terminal/TerminalSession.tsx`: clear UI buffers on every lifecycle path, add safe status/retry rendering, configure xterm defensively, and retain transport ownership boundaries.
- Modify `frontend/src/styles.css`: expand only the active device terminal and fix responsive terminal sizing.

### Tests and status

- Create `backend/tests/unit/test_ssh_compatibility.py` and `backend/tests/unit/test_connection_gate.py`.
- Modify backend migration, config, driver, queue, logging, device, discovery, and terminal tests listed in the tasks below.
- Modify frontend device-form, inspector, terminal-input, terminal-panel, USB, and serving-policy tests listed below.
- Modify `docs/IMPLEMENTATION_STATUS.md`, `docs/CAPABILITY_MATRIX.md`, `docs/lab-test-guide.md`, `docs/safety-model.md`, and `docs/user-guide.md` only after automated verification.

---

### Task 1: Add the versioned compatibility domain, settings, and migration

**Files:**
- Create: `backend/app/drivers/ssh_compatibility.py`
- Create: `backend/migrations/versions/20260722_0003_legacy_ssh.py`
- Create: `backend/tests/unit/test_ssh_compatibility.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/devices.py`
- Modify: `backend/app/drivers/base.py`
- Modify: `backend/app/core/config.py`
- Modify: `.env.example`
- Modify: `deploy/compose.yml`
- Modify: `backend/tests/unit/test_config.py`
- Modify: `backend/tests/integration/test_migrations.py`
- Modify: `backend/tests/integration/test_model_invariants.py`
- Modify: `.env.example`
- Modify: `deploy/compose.yml`

**Interfaces:**

```python
class SSHCompatibility(StrEnum):
    MODERN = "modern"
    CISCO_LEGACY = "cisco_legacy"
    CISCO_LEGACY_GROUP1 = "cisco_legacy_group1"

SSH_COMPATIBILITY_POLICY_VERSION = 1

@dataclass(frozen=True, slots=True)
class SSHCompatibilityPolicy:
    mode: SSHCompatibility
    version: int
    openssh_options: tuple[str, ...]
    asyncssh_kex_algs: str | None
    asyncssh_server_host_key_algs: str | None
    asyncssh_encryption_algs: str | None
    asyncssh_mac_algs: str | None

def compatibility_policy(mode: SSHCompatibility) -> SSHCompatibilityPolicy: ...
def enforce_compatibility_policy(
    mode: SSHCompatibility,
    settings: Settings,
    *,
    group1_risk_acknowledged: bool,
) -> None: ...
```

- [ ] **Step 1: Run impact analysis before touching existing symbols**

Run GitNexus upstream impact for `Device`, `DeviceConnectionFields`, `ConnectionParameters`, and `Settings`. Record the direct callers and affected processes in the task notes. The previously observed `ConnectionParameters` result was MEDIUM; re-check against the current index.

- [ ] **Step 2: Write failing policy, settings, model, and migration tests**

In `test_ssh_compatibility.py`, assert the exact values and order:

```python
assert compatibility_policy(SSHCompatibility.MODERN).openssh_options == ()
assert compatibility_policy(SSHCompatibility.CISCO_LEGACY).openssh_options == (
    "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1",
    "HostKeyAlgorithms=+ssh-rsa",
    "Ciphers=+aes256-cbc,aes192-cbc,aes128-cbc",
    "MACs=+hmac-sha1,hmac-sha1-96",
)
assert "diffie-hellman-group1-sha1" not in " ".join(
    compatibility_policy(SSHCompatibility.CISCO_LEGACY).openssh_options
)
assert compatibility_policy(SSHCompatibility.CISCO_LEGACY_GROUP1).version == 1
```

Parametrize prohibited values (`ssh-dss`, `hmac-md5`, `3des-cbc`, `arcfour`) and assert they are absent from both OpenSSH and AsyncSSH policy outputs. Assert legacy and Group1 settings default false, terminal defaults true, and Group1 requires both the server switch and request acknowledgment.

Add migration tests which upgrade the phase-2 schema, verify every pre-existing row reads `modern`, reject null/unknown values, and downgrade cleanly.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/unit/test_ssh_compatibility.py tests/unit/test_config.py tests/integration/test_migrations.py tests/integration/test_model_invariants.py -q
```

Expected: imports and schema assertions fail because the compatibility domain does not exist.

- [ ] **Step 4: Implement the smallest immutable policy and schema**

Add `ssh_compatibility` to `Device` with database enum values matching `SSHCompatibility`, default `modern`, and `nullable=False`. Add the value to `DeviceConnectionFields`, `DeviceUpdate`, `DeviceView`, and `ConnectionParameters`. Add only this ephemeral request field; do not persist it:

```python
group1_risk_acknowledged: bool = False
```

Use `+`-prefixed AsyncSSH strings so modern defaults remain first. Add settings:

```python
ssh_legacy_enabled: bool = False
ssh_group1_enabled: bool = False
ssh_terminal_enabled: bool = True
terminal_pty_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
terminal_max_duration_seconds: int = Field(default=3600, ge=60, le=86400)
```

Expose only non-secret values in `.env.example` and the shared API/worker Compose environment. Change the API command to include `--ws-max-size 8192`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the command from Step 3. Expected: all selected tests pass, with migrated devices defaulting to `modern`.

- [ ] **Step 6: Check scope and commit**

Run GitNexus `detect_changes({scope: "compare", base_ref: "main"})`, then commit only Task 1 files:

```text
git commit -m "feat(backend): define legacy SSH policy"
```

---

### Task 2: Apply password-only policy and sanitized errors to Scrapli

**Files:**
- Create: `backend/app/drivers/ssh_errors.py`
- Modify: `backend/app/drivers/transport.py`
- Modify: `backend/app/drivers/generic_readonly.py`
- Modify: `backend/app/drivers/cisco_iosxe.py`
- Modify: `backend/app/core/errors.py`
- Modify: `backend/app/core/logging.py`
- Modify: `backend/tests/unit/test_drivers.py`
- Modify: `backend/tests/unit/test_logging.py`
- Modify: `backend/tests/integration/test_device_vertical_slice.py`

**Interfaces:**

```python
class ConnectionPhase(StrEnum):
    TCP = "tcp_connection"
    NEGOTIATION = "ssh_negotiation"
    HOST_KEY = "host_key_verification"
    AUTHENTICATION = "authentication"
    PTY = "pty_creation"
    TERMINAL_IO = "terminal_io"

@dataclass(frozen=True, slots=True)
class SanitizedSSHFailure:
    code: str
    phase: ConnectionPhase
    retryable: bool
    recommended_action: str | None

def translate_ssh_error(exc: Exception, *, phase: ConnectionPhase) -> AppError: ...
def password_only_openssh_options(policy: SSHCompatibilityPolicy) -> tuple[str, ...]: ...
```

- [ ] **Step 1: Run impact analysis**

Run upstream impact for `ScrapliTransport`, `ScrapliGenericTransport`, and `translate_transport_error`. Warn before editing if current risk is HIGH or CRITICAL.

- [ ] **Step 2: Write failing exact-constructor and sanitization tests**

Capture both Scrapli constructor dictionaries and assert `transport_options` contains only separate `-o` argument pairs for:

```text
IdentityAgent=none
IdentitiesOnly=yes
PreferredAuthentications=password
PasswordAuthentication=yes
PubkeyAuthentication=no
KbdInteractiveAuthentication=no
HostbasedAuthentication=no
GSSAPIAuthentication=no
NumberOfPasswordPrompts=1
```

Assert modern adds no algorithm flags, legacy adds the exact four policy flags, Group1 adds only the approved fifth KEX value, and neither password nor enable password occurs in the flattened `open_cmd` list. Assert both Cisco and generic transports receive the same authentication policy.

Parametrize real Scrapli exceptions and safe connection phases. Assert every mapped `AppError.details` is exactly `phase`, `retryable`, and optional fixed `recommended_action`; raw markers, exception class names, peer-offered lists, hostnames, and credentials must be absent from `str(error)`, API JSON, logs, and formatted worker exceptions.

- [ ] **Step 3: Run tests and verify RED**

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/unit/test_drivers.py tests/unit/test_logging.py tests/integration/test_device_vertical_slice.py -q
```

Expected: transport option assertions and phase metadata tests fail.

- [ ] **Step 4: Implement request-scoped OpenSSH options and fixed error catalog**

Pass options through Scrapli's supported seam:

```python
"transport_options": {"open_cmd": list(password_only_openssh_options(policy))}
```

Do not build a new SSH subprocess and do not include secrets in `open_cmd`. Map typed exceptions first. Where a library exposes only a generic transport error, inspect it in memory only long enough to choose a fixed code, discard the raw string, and raise the sanitized error `from None`.

Use a fixed catalog such as:

```python
FAILURES = {
    "device_authentication_failed": SanitizedSSHFailure(
        "device_authentication_failed",
        ConnectionPhase.AUTHENTICATION,
        False,
        "Verify the selected credential profile and device login policy.",
    ),
    "legacy_ssh_negotiation_failed": SanitizedSSHFailure(
        "legacy_ssh_negotiation_failed",
        ConnectionPhase.NEGOTIATION,
        False,
        "Verify the saved compatibility mode for this device.",
    ),
}
```

Keep every user-facing action in this catalog, not in exception text.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run Step 3 again. Expected: all tests pass and no raw marker appears in captured output.

- [ ] **Step 6: Check scope and commit**

Run `detect_changes` against `main`, then commit:

```text
git commit -m "fix(backend): scope legacy SSH transport"
```

---

### Task 3: Add the shared Redis connection gate

**Files:**
- Create: `backend/app/services/connection_gate.py`
- Create: `backend/tests/unit/test_connection_gate.py`
- Modify: `backend/app/container.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/fakes.py`
- Modify: `backend/tests/unit/test_config.py`

**Interfaces:**

```python
class ConnectionOperation(StrEnum):
    CONNECTION_TEST = "connection_test"
    STRUCTURED_READ = "structured_read"
    TERMINAL = "terminal"

@dataclass(frozen=True, slots=True)
class ConnectionTarget:
    endpoint_digest: str
    credential_profile_id: UUID
    device_id: UUID | None

@dataclass(frozen=True, slots=True)
class ConnectionPermit:
    identifier: str
    operation: ConnectionOperation
    target: ConnectionTarget

class ConnectionGate(Protocol):
    def acquire(self, operation: ConnectionOperation, target: ConnectionTarget) -> ConnectionPermit: ...
    def authentication_succeeded(self, target: ConnectionTarget) -> None: ...
    def authentication_failed(self, target: ConnectionTarget) -> None: ...
    def release(self, permit: ConnectionPermit) -> None: ...
```

- [ ] **Step 1: Run impact analysis**

Run upstream impact for `ApplicationContainer`, `reserve_terminal_session`, and `release_terminal_session`. The last two will be removed only after all callers move to the gate.

- [ ] **Step 2: Write failing gate tests with a fake Redis clock/store**

Cover these exact defaults and boundaries:

- fifth connection-test attempt per endpoint/profile in 60 seconds is allowed; sixth is denied;
- fifth terminal-open attempt per device in 60 seconds is allowed; sixth is denied;
- third authentication failure activates a 60-second cooldown;
- authentication success clears only that tuple's failure counter;
- negotiation, host-key, PTY, and network failures never call `authentication_failed`;
- global connection limit uses `MAX_DEVICE_CONNECTIONS`;
- per-device SSH, global terminal, and per-device terminal limits are three;
- expired permit TTL restores capacity after a simulated process death;
- release is idempotent;
- Redis errors fail closed with `connection_gate_unavailable`;
- Redis keys contain a digest and opaque IDs, never the target address or hostname.

- [ ] **Step 3: Run tests and verify RED**

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/unit/test_connection_gate.py tests/unit/test_config.py -q
```

Expected: gate imports and settings fail.

- [ ] **Step 4: Implement one atomic Redis gate and injectable fake**

Use Redis Lua scripts or a transaction so admission cannot exceed limits between check and increment. Store a permit key with a bounded TTL and one set entry per global/device dimension. Build the endpoint component with a normalized host/port/profile digest before Redis access:

```python
endpoint_digest = hashlib.sha256(
    f"{host.lower()}:{port}:{profile_id}".encode("utf-8")
).hexdigest()
```

Never store the preimage. Use a synchronous gate for FastAPI and workers; the terminal task will call it through `asyncio.to_thread` so the event loop does not block. Keep `FakeConnectionGate` in tests and inject it through `ApplicationContainer`.

- [ ] **Step 5: Run tests and verify GREEN**

Run Step 3 again. Expected: all limit, TTL, idempotency, fail-closed, and privacy tests pass.

- [ ] **Step 6: Check scope and commit**

Run `detect_changes`, verify the old in-process terminal counter is no longer referenced, then commit:

```text
git commit -m "feat(backend): gate SSH connections in Redis"
```

---

### Task 4: Gate all structured connection paths and enforce fresh save tests

**Files:**
- Modify: `backend/app/services/devices.py`
- Modify: `backend/app/services/snapshots.py`
- Modify: `backend/app/api/devices.py`
- Modify: `backend/app/api/discovery.py`
- Modify: `backend/app/jobs/tasks.py`
- Modify: `backend/tests/integration/test_device_vertical_slice.py`
- Modify: `backend/tests/integration/test_discovery_vertical_slice.py`
- Modify: `backend/tests/integration/test_diagnostics_vertical_slice.py`
- Modify: `backend/tests/unit/test_queue.py`

**Interfaces:**

```python
@contextmanager
def admitted_connection(
    self,
    *,
    device_id: UUID | None,
    host: str,
    port: int,
    profile_id: UUID,
    compatibility: SSHCompatibility,
    group1_risk_acknowledged: bool,
    operation: ConnectionOperation,
) -> Iterator[ConnectionParameters]: ...
```

- [ ] **Step 1: Run impact analysis**

Run upstream impact for `DeviceService`, `DeviceService.connection_parameters`, `SnapshotService.capture`, and `execute_job`. The prior `DeviceService` risk was MEDIUM; re-check before edits.

- [ ] **Step 2: Add failing vertical-slice tests**

Assert:

- direct add, edit, candidate connection test, registered-device test, and discovery approval default to `modern`;
- create always executes a fresh backend test even after a successful browser test;
- changing address, port, vendor, credential profile, or compatibility executes a fresh test before save;
- a failed retest does not mutate the saved device;
- discovery never selects or escalates compatibility;
- Group1 requests without acknowledgment return the stable policy code;
- disabled legacy or Group1 policy fails before constructing a driver and does not mutate status;
- refresh, diagnostics, and snapshot reads acquire and idempotently release one permit;
- auth failures increment only the correct digested tuple and success clears it;
- queue arguments remain only opaque job IDs and persisted RQ failures contain sanitized fields only;
- audit events identify only `local-admin`, internal device ID, timestamp, requested mode, Group1 state, policy version, operation, phase, authorization decision, bounded duration, and result code, with no negotiated algorithm or target address.

- [ ] **Step 3: Run focused tests and verify RED**

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/integration/test_device_vertical_slice.py tests/integration/test_discovery_vertical_slice.py tests/integration/test_diagnostics_vertical_slice.py tests/unit/test_queue.py -q
```

- [ ] **Step 4: Implement one admitted connection scope**

Make `DeviceService.admitted_connection()` the only structured path which resolves credentials and yields `ConnectionParameters`. Order the scope as:

1. normalize and validate policy;
2. acquire permit without decrypting credentials;
3. decrypt the selected profile just in time;
4. call the driver inside the scope;
5. update auth counters only for the sanitized authentication result;
6. release local references and the Redis permit in `finally`.

Update `SnapshotService.capture()` to use this scope instead of calling `connection_parameters()` directly. Keep RQ payloads unchanged. Use `from None` when rethrowing sanitized worker failures.

- [ ] **Step 5: Run tests and verify GREEN**

Run Step 3 again. Expected: every structured path is admitted, denial is fail-closed, and no fake opens a network connection.

- [ ] **Step 6: Check scope and commit**

Run `detect_changes`, then commit:

```text
git commit -m "fix(backend): enforce SSH policy on reads"
```

---

### Task 5: Rebuild the device terminal boundary around the same policy

**Files:**
- Modify: `backend/app/api/terminal.py`
- Modify: `backend/tests/integration/test_terminal_vertical_slice.py`
- Modify: `deploy/compose.yml`

**Interfaces:**

WebSocket client acknowledgment:

```json
{"type":"accept_direct_mode","group1_risk_acknowledged":false}
```

Sanitized server error:

```json
{
  "type":"error",
  "code":"legacy_ssh_negotiation_failed",
  "message":"Unable to negotiate a compatible SSH session.",
  "phase":"ssh_negotiation",
  "retryable":false,
  "recommended_action":"Verify the saved compatibility mode for this device."
}
```

- [ ] **Step 1: Run impact analysis**

Run upstream impact for `terminal`, `_open_terminal`, and `_connection_parameters`. Confirm the WebSocket execution flow and all cleanup callers before edits.

- [ ] **Step 2: Add failing terminal boundary tests**

Extend the fake AsyncSSH connection/process to cover:

- modern, legacy, and Group1 produce the exact `config=None`, `client_keys=None`, `agent_path=None`, `preferred_auth="password"`, `password_auth=True`, `public_key_auth=False`, `kbdint_auth=False`, `host_based_auth=False`, `gss_auth=False`, and additive algorithm kwargs;
- strict host-key behavior is unchanged by compatibility mode;
- terminal kill switch, legacy kill switch, Group1 kill switch, missing Group1 acknowledgment, admission limit, cooldown, and Redis failure all deny before SSH opens;
- connection-open timeout, PTY timeout, shell rejection, idle timeout, and 60-minute maximum duration emit fixed sanitized codes;
- decoded input above 4 KiB, output above 2 MiB, and frames above the Uvicorn limit fail closed;
- slow WebSocket sends prevent another SSH read, proving sequential backpressure;
- success, client close, read/write failure, cancellation, timeout, and app shutdown all close process/connection and release the permit exactly once;
- raw exceptions, credentials, commands, peer algorithms, and terminal output never enter WebSocket errors, events, logs, or database records.

- [ ] **Step 3: Run tests and verify RED**

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/integration/test_terminal_vertical_slice.py -q
```

- [ ] **Step 4: Implement AsyncSSH policy, time bounds, and cleanup**

Keep the current separate terminal transport. Construct AsyncSSH kwargs from the same compatibility policy immediately before `asyncssh.connect()`. Bound the existing open operation with `ssh_connect_timeout_seconds`, then bound PTY/shell creation separately:

```python
process = await asyncio.wait_for(
    connection.create_process(term_type="xterm-256color"),
    timeout=settings.terminal_pty_timeout_seconds,
)
```

Use one idempotent `cleanup()` which first blocks input/cancels relays, then closes process/channel, connection, WebSocket, releases the Redis permit, and drops policy/credential references. Keep sequential `read(4096)` followed by awaited `send_json()`; do not add an output queue. Run synchronous gate calls with `asyncio.to_thread`.

- [ ] **Step 5: Run terminal tests and verify GREEN**

Run Step 3 again. Expected: every branch is network-free and passes.

- [ ] **Step 6: Check scope and commit**

Run `detect_changes`, verify only the terminal flow and Compose frame limit changed, then commit:

```text
git commit -m "fix(backend): harden legacy SSH terminal"
```

---

### Task 6: Add compatibility controls to Add, Edit, and discovery approval

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/network.ts`
- Modify: `frontend/src/features/inventory/DeviceForm.tsx`
- Modify: `frontend/src/features/inventory/InventoryPage.tsx`
- Modify: `frontend/src/features/inventory/DeviceInspector.tsx`
- Modify: `frontend/tests/device-form.test.tsx`
- Modify: `frontend/tests/device-inspector.test.tsx`
- Modify: `frontend/tests/discovery-dialog.test.tsx`

**Interfaces:**

```ts
export type SshCompatibility = 'modern' | 'cisco_legacy' | 'cisco_legacy_group1';

export interface DeviceInput {
  // existing fields
  ssh_compatibility: SshCompatibility;
  group1_risk_acknowledged: boolean;
}
```

- [ ] **Step 1: Run impact analysis**

Run upstream impact for `DeviceForm`, `DeviceInput`, `InventoryPage`, and `DeviceInspector`.

- [ ] **Step 2: Write failing UI/API tests**

Assert:

- new Add and discovery approval forms default to Modern;
- Edit loads the saved value;
- Legacy explains that the exception is per-device and never an automatic fallback;
- Group1 shows a last-resort warning and requires a separate unchecked acknowledgment;
- test and save requests contain mode and acknowledgment;
- changing mode or acknowledgment invalidates a previous successful test and disables Save;
- a policy-denied API error shows only sanitized message/action;
- saved legacy devices display `LEGACY SSH`, while modern devices do not;
- discovery candidates are not labeled legacy until the operator selects it in DeviceForm.

- [ ] **Step 3: Run tests and verify RED**

```text
cd frontend
npm test -- --run tests/device-form.test.tsx tests/device-inspector.test.tsx tests/discovery-dialog.test.tsx
```

- [ ] **Step 4: Implement the minimal form and badge changes**

Add a select with the three exact enum values. Include compatibility and Group1 acknowledgment in the existing connection fingerprint. Do not cache a successful test token and do not add compatibility to credential profiles. Keep backend errors authoritative.

- [ ] **Step 5: Run tests and verify GREEN**

Run Step 3 again. Expected: Add, Edit, and discovery approval all use the same form contract.

- [ ] **Step 6: Check scope and commit**

Run `detect_changes`, then commit:

```text
git commit -m "feat(frontend): select legacy SSH per device"
```

---

### Task 7: Harden the shared terminal session and SSH paste behavior

**Files:**
- Modify: `frontend/src/features/terminal/transport.ts`
- Modify: `frontend/src/features/terminal/SshWebSocketTransport.ts`
- Modify: `frontend/src/features/terminal/inputPolicy.ts`
- Modify: `frontend/src/features/terminal/TerminalSession.tsx`
- Modify: `frontend/src/features/inventory/TerminalPanel.tsx`
- Modify: `frontend/tests/terminal-input-policy.test.ts`
- Modify: `frontend/tests/terminal-panel.test.tsx`
- Modify: `frontend/tests/usb-console-dialog.test.tsx`
- Modify: `frontend/tests/usb-serial-transport.test.ts`

**Interfaces:**

```ts
export interface TerminalFailure {
  code: string;
  message: string;
  phase?: string;
  retryable: boolean;
  recommendedAction?: string;
}

export interface PreparedTerminalInput {
  data: string;
  lineCount: number;
  characterCount: number;
  byteCount: number;
  containsUnsafeControl: boolean;
  requiresConfirmation: boolean;
}
```

- [ ] **Step 1: Run and report HIGH-risk impact analysis**

Run upstream impact for `TerminalSession`, `prepareTerminalInput`, `SshWebSocketTransport`, and `TerminalPanel`. `TerminalSession` previously returned HIGH with direct impact on both `TerminalPanel` and `UsbConsoleDialog`; explicitly report this before editing.

- [ ] **Step 2: Write failing input and session tests**

Test normalized CR/LF/CRLF detection while preserving the bytes actually sent in raw mode. Require confirmation when any condition is true:

```ts
lineCount > 1 || characterCount > 1_024 || containsUnsafeControl
```

Allow only tab, carriage return, and line feed from the control-character range. Reject pending input above 4,096 UTF-8 bytes before storing it. Confirmation must render only line and character counts, never command content.

Add lifecycle tests proving pending input clears after send, cancel, write failure, open failure, retry, tab switch, tab removal, pagehide, route/component teardown, disconnect, cleanup timeout, and normal close. Assert a retryable error shows Retry and creates fresh WebSocket/xterm objects; a non-retryable auth/host-key/negotiation/PTY/policy error shows fixed guidance without Retry.

Assert xterm is created with proposed APIs and window operations disabled and `linkHandler: null`; no clipboard, download, notification, web-link addon, custom OSC handler, or title handler is registered. Spy on browser storage, `fetch`, WebSocket construction, analytics-like globals, `window.open`, clipboard, notifications, and downloads to prove output/errors cause no privileged or persistence action.

- [ ] **Step 3: Run tests and verify RED**

```text
cd frontend
npm test -- --run tests/terminal-input-policy.test.ts tests/terminal-panel.test.tsx tests/usb-console-dialog.test.tsx tests/usb-serial-transport.test.ts
```

- [ ] **Step 4: Implement typed errors, safe paste, and fresh retry**

Extend only UI-level buffers in `TerminalSession`; raw WebSocket state stays in `SshWebSocketTransport`, and USB readers/writers/decoder/queues remain exclusively in `UsbSerialTransport`. Add an `active` prop so a tab switch clears only pending confirmation input without transferring transport ownership.

Configure xterm explicitly:

```ts
const nextTerminal = new Terminal({
  allowProposedApi: false,
  windowOptions: {},
  linkHandler: null,
  // retain existing visual options
});
```

Set SSH input policy to raw line endings with paste confirmation enabled. Send `group1_risk_acknowledged` only in the initial Direct Mode acknowledgment. Retry calls the normal `open()` path after the completed shared teardown; it must never reuse the socket, xterm instance, session token, or pending input.

- [ ] **Step 5: Run the shared-session and USB regression gate**

Run Step 3 again, then:

```text
cd frontend
npm test -- --run tests/usb-console-styles.test.ts tests/serving-policy.test.ts
```

Expected: all SSH and USB tests pass. No USB serial ownership, cleanup, fake-stream, backend-traffic, or visual behavior regresses.

- [ ] **Step 6: Check scope and commit**

Run `detect_changes` and confirm the reported HIGH-risk flow is limited to shared terminal consumers and their tests. Commit:

```text
git commit -m "fix(frontend): harden direct terminal sessions"
```

---

### Task 8: Expand only the active device terminal UI

**Files:**
- Modify: `frontend/src/features/inventory/DeviceInspector.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/tests/device-inspector.test.tsx`
- Modify: `frontend/tests/terminal-panel.test.tsx`
- Modify: `frontend/tests/usb-console-styles.test.ts`

- [ ] **Step 1: Run impact analysis**

Run upstream impact for `DeviceInspector` and `TerminalPanel`. Inspect the `workspace-layout` flow before changing responsive CSS.

- [ ] **Step 2: Add failing layout and accessibility tests**

Assert the inspector gets `inspector--terminal` only while Terminal is active; Overview and all other tabs retain the existing class and width. Assert CSS contains:

```css
.workspace-layout:has(> .inspector--terminal) {
  grid-template-columns: minmax(0, 1fr) min(680px, 48vw);
}

.terminal-session__canvas {
  height: clamp(360px, 55vh, 620px);
}

@media (max-width: 1020px) {
  .inspector--terminal {
    width: min(680px, calc(100vw - 74px));
  }
}
```

Also assert the seven inspector tabs use seven grid columns, terminal session tabs expose selected/focus state and close labels, and no horizontal page overflow is introduced. Retain USB modal width/style assertions unchanged.

- [ ] **Step 3: Run tests and verify RED**

```text
cd frontend
npm test -- --run tests/device-inspector.test.tsx tests/terminal-panel.test.tsx tests/usb-console-styles.test.ts
```

- [ ] **Step 4: Implement the terminal-only modifier and compact status UI**

Use `className={tab === 'terminal' ? 'inspector inspector--terminal' : 'inspector'}`. Do not lift layout state, add resizable panels, or alter USB Direct Mode. Keep the warning visible, but lay out warning/status/error/actions compactly inside the larger terminal panel.

- [ ] **Step 5: Run tests and verify GREEN**

Run Step 3 again. Expected: terminal layout tests pass and USB style tests are unchanged.

- [ ] **Step 6: Check scope and commit**

Run `detect_changes`, then commit:

```text
git commit -m "fix(frontend): expand device terminal workspace"
```

---

### Task 9: Verify the full slice and record conservative status

**Files:**
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/lab-test-guide.md`
- Modify: `docs/safety-model.md`
- Modify: `docs/user-guide.md`
- Retain unchanged: `docs/network-automation-final-plan.md`
- Retain: `docs/superpowers/specs/2026-07-22-cisco-legacy-ssh-terminal-design.md`

- [ ] **Step 1: Run complete backend verification without lab opt-ins**

```text
cd backend
.venv/Scripts/python.exe -m ruff check --no-cache .
.venv/Scripts/pyright.exe
.venv/Scripts/python.exe -m pytest
```

Expected: Ruff passes, Pyright reports zero errors, routine tests pass, lab tests remain skipped, and no external/device traffic occurs.

- [ ] **Step 2: Run complete frontend verification**

```text
cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

Expected: all commands exit zero.

- [ ] **Step 3: Validate both Compose configurations**

```text
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.yml -f deploy/compose.dev.yml config --quiet
```

Expected: both commands exit zero. Do not start a device connection.

- [ ] **Step 4: Run explicit secret, persistence, and network-regression scans**

Run focused tests for raw markers, queue arguments, Redis keys, terminal WebSocket messages, storage APIs, backend fetch/WebSocket traffic from USB Direct Mode, and xterm privileged actions. Search the diff for `password`, `private key`, raw exception markers, literal lab addresses, `localStorage`, `sessionStorage`, `indexedDB`, telemetry calls, and terminal-content logging; inspect every match rather than relying on the search alone.

- [ ] **Step 5: Update documentation conservatively**

Record:

- `compatibility_policy_version = 1` and the exact allowed algorithms;
- all three server kill switches and operational limits;
- modern remains the default and no fallback exists;
- host-key policy is unchanged;
- device terminal and USB terminal are manual Direct Mode and can change hardware;
- routine verification is network-free;
- status wording is exactly **Automated verification passed; hardware validation pending**.

In `CAPABILITY_MATRIX.md`, keep Cisco legacy SSH terminal and topology claims lab-unverified until a separately authorized test is recorded. The optional hardware record may contain only date, approver, browser, adapter/transport type, device category, application commit, requested compatibility mode, validation-step descriptions, and pass/fail. It must not contain addresses, hostnames, serial numbers, credentials, commands, terminal output, configuration, screenshots, raw errors, or session content.

- [ ] **Step 6: Review specification coverage and plan exclusions**

Check each approved design section against implementation and tests. Confirm no Telnet/FTP, automatic fallback, algorithm discovery, graph configuration, structured writes, RBAC facade, active-session registry, generated commands, vendor templates, or phase-3 code was added.

- [ ] **Step 7: Run final GitNexus change detection**

Run GitNexus `detect_changes({scope: "compare", base_ref: "main"})`. Inspect every affected symbol and execution flow. Resolve unexpected scope before committing.

- [ ] **Step 8: Commit verification and status**

```text
git commit -m "docs: record legacy SSH verification status"
```

- [ ] **Step 9: Request code review before integration**

Invoke `superpowers:requesting-code-review`. Address findings with `superpowers:receiving-code-review`, rerun the complete verification commands, and use `superpowers:verification-before-completion` before claiming the slice is ready to merge.
