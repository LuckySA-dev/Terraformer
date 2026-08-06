# Phase 1-2 Readiness Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the concrete Phase 1-2 security and usability blockers, then produce current-build automated and separately authorized lab evidence without adding structured writes.

**Architecture:** Add one mandatory per-device SSH host-key trust path shared by connection tests, structured reads, and the SSH terminal. Keep the existing read-only drivers, RQ jobs, Direct Mode boundaries, and loopback deployment; fix only stale/error/focus/responsive UI states that block Phase 1-2 operation.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, Redis, AsyncSSH, Scrapli, React 19, TanStack Query, Vitest, Pytest.

## Global Constraints

- Treat every target as real hardware; routine tests must use fakes and must not open network sockets.
- Host-key verification is mandatory; unknown or changed keys fail closed with no global fallback.
- First contact collects a public host key only; it does not authenticate or run a command.
- Remove `SSH_STRICT_HOST_KEY` and `LAB_SSH_STRICT_HOST_KEY`; there is no relaxed runtime mode.
- Preserve the existing legacy SSH policy: modern by default, no automatic fallback, Group1 requires its existing per-device acknowledgment and policy switch.
- Do not persist or expose credentials, terminal content, raw configuration, raw exceptions, or peer-offered algorithm lists.
- Lab evidence contains metadata and pass/fail results only; virtual and physical evidence remain separate.
- Do not change `docs/network-automation-final-plan.md`.
- P2 cosmetic redesign, animation, backup/restore, and any structured write are outside this plan.

---

## File Structure

- `docs/PHASE_1_2_READINESS.md`: requirement-by-requirement conformance and evidence ledger.
- `backend/app/services/ssh_trust.py`: exact-target host-key candidate collection, Redis candidate binding, and pinned trust resolution.
- `backend/app/models/entities.py`: one pinned SSH host-key record per registered device.
- `backend/app/repositories/ssh_trust.py`: trust record persistence only.
- `backend/app/schemas/ssh_trust.py`: candidate and trust API contracts with no key material beyond the public OpenSSH key.
- `backend/app/api/ssh_trust.py`: authenticated first-contact and trust-status endpoints.
- `backend/migrations/versions/20260806_0004_device_ssh_host_keys.py`: trust table and one-device uniqueness.
- `backend/app/drivers/base.py`, `backend/app/drivers/transport.py`: carry exact known-hosts material into every Scrapli connection.
- `backend/app/api/terminal.py`: use the same pinned trust in AsyncSSH.
- `frontend/src/features/inventory/DeviceForm.tsx`: collect, display, and confirm first-contact fingerprint before connection testing.
- `frontend/src/features/inventory/DeviceInspector.tsx`, `TerminalPanel.tsx`, `TopologyPage.tsx`, `styles.css`: blocking terminal/topology error, focus, and responsive states only.
- `backend/tests/lab/test_cisco_iosxe_lab.py`: mandatory known-hosts preflight; still skipped by default.

### Task 1: Freeze the Phase 1-2 conformance ledger

**Files:**
- Create: `docs/PHASE_1_2_READINESS.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Test: `docs/PHASE_1_2_READINESS.md` (document check)

**Interfaces:**
- Consumes: Phase 1-2 requirements in `docs/network-automation-final-plan.md`, current status and capability matrix.
- Produces: rows with `Requirement | Backend | Frontend | Automated | Virtual lab | Physical lab | Priority | Status` and the fixed P0/P1 list below.

- [ ] **Step 1: Write the failing document check**

```powershell
$required = 'Manual add','Host-key trust','Facts','Interfaces','Snapshot','Discovery','CDP/LLDP','Topology','Terminal','Diagnostics'
$text = Get-Content -Raw docs/PHASE_1_2_READINESS.md
$required | ForEach-Object { if ($text -notmatch [regex]::Escape($_)) { throw "missing readiness row: $_" } }
```

- [ ] **Step 2: Run it to verify it fails**

Run from repository root. Expected: FAIL because `docs/PHASE_1_2_READINESS.md` does not exist.

- [ ] **Step 3: Create the minimal ledger**

Record these findings explicitly; do not invent a lab pass:

```markdown
| Requirement | Backend | Frontend | Automated | Virtual lab | Physical lab | Priority | Status |
|---|---|---|---|---|---|---|---|
| Host-key trust | Global strict toggle only; no device pin | No enrollment flow | Error mapping only | Pending | Pending | P0 | Missing implementation |
| Manual add | Implemented | Implemented | Passed | Pending | Pending | P1 | Hardware validation pending |
| Facts/interfaces/snapshot | Implemented | Implemented | Passed | Pending | Pending | P1 | Hardware validation pending |
| Discovery and approval | Implemented | Implemented | Passed | Pending | Not provable by one physical device | P1 | Hardware validation pending |
| CDP/LLDP topology | Implemented | Stale refresh replaces useful graph with error | Passed | Pending | Not provable by one physical device | P1 | UI gap plus hardware validation pending |
| SSH terminal | Implemented | Blocking responsive/focus/error guidance gaps | Passed | Pending | Pending | P1 | UI gap plus hardware validation pending |
| Diagnostics | Implemented | Failed job banner does not clearly preserve failure state | Passed | Pending | Pending | P1 | UI gap plus hardware validation pending |
```

Add a short classification rule: implementation missing, automated verification passed, and hardware validation pending are distinct states. Mark cosmetic polish and Phase 0 backup/restore as P2/outside this closure.

- [ ] **Step 4: Run the document check**

Expected: PASS with no output.

- [ ] **Step 5: Commit**

```powershell
git add docs/PHASE_1_2_READINESS.md docs/IMPLEMENTATION_STATUS.md
git commit -m "docs: freeze Phase 1-2 readiness gaps"
```

### Task 2: Add mandatory exact-device SSH host-key trust

**Files:**
- Create: `backend/app/services/ssh_trust.py`
- Create: `backend/app/repositories/ssh_trust.py`
- Create: `backend/app/schemas/ssh_trust.py`
- Create: `backend/app/api/ssh_trust.py`
- Create: `backend/migrations/versions/20260806_0004_device_ssh_host_keys.py`
- Modify: `backend/app/models/entities.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/container.py`
- Modify: `backend/app/core/errors.py`
- Test: `backend/tests/unit/test_ssh_trust.py`
- Test: `backend/tests/integration/test_device_vertical_slice.py`
- Test: `backend/tests/integration/test_migrations.py`

**Interfaces:**
- Consumes: `asyncssh.get_server_host_key()`, Redis, `SSHCompatibility`, authenticated FastAPI dependencies.
- Produces: `HostKeyCandidateStore.create(request, material) -> HostKeyCandidate`, `await HostKeyTrustService.collect_candidate(request) -> HostKeyCandidateView`, `resolve_known_hosts(device_id, candidate_id) -> str`, and `DeviceSSHHostKey` one-to-one persistence.

- [ ] **Step 1: Write failing unit and API tests**

```python
def test_candidate_is_bound_to_exact_endpoint_profile_and_mode(fake_redis, fake_key_probe):
    service = trust_service(fake_redis, fake_key_probe)
    candidate = service.collect_candidate(candidate_request())
    assert candidate.algorithm == "ssh-rsa"
    assert candidate.fingerprint.startswith("SHA256:")
    with pytest.raises(HostKeyCandidateMismatchError):
        service.resolve_candidate(candidate.id, candidate_request(port=2222))


def test_changed_registered_key_fails_before_credentials_or_commands(client, seeded_device, monkeypatch):
    install_changed_key_transport(monkeypatch)
    response = client.post(f"/api/devices/{seeded_device.id}/test-connection")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "device_host_key_changed"
    assert transport_authentication_attempts() == 0
```

Migration assertions:

```python
assert {"device_id", "algorithm", "public_key", "fingerprint", "confirmed_at", "confirmed_by"} <= columns("device_ssh_host_keys")
assert unique_columns("device_ssh_host_keys") == {"device_id"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_ssh_trust.py tests/integration/test_device_vertical_slice.py tests/integration/test_migrations.py -q`

Expected: FAIL because the trust service, API, model, and migration do not exist.

- [ ] **Step 3: Add the trust model and contracts**

```python
class DeviceSSHHostKey(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "device_ssh_host_keys"
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="local-admin")
```

```python
class HostKeyCandidateRequest(DeviceConnectionFields):
    pass

class HostKeyCandidateView(APIModel):
    id: UUID
    algorithm: str
    fingerprint: str
    expires_at: datetime
```

Candidate Redis payload contains only candidate UUID, endpoint/profile/mode digests, algorithm, public OpenSSH key, fingerprint, and 15-minute expiry. It contains no password and is never logged. The candidate endpoint is `POST /api/ssh-host-key-candidates`; registered trust status is `GET /api/devices/{device_id}/ssh-host-key`.

- [ ] **Step 4: Implement exact-target collection and resolution**

```python
async def probe_host_key(host: str, port: int, mode: SSHCompatibility) -> HostKeyMaterial:
    policy = compatibility_policy(mode)
    values = {
        name: value
        for name, value in (
            ("kex_algs", policy.asyncssh_kex_algs),
            ("server_host_key_algs", policy.asyncssh_server_host_key_algs),
            ("encryption_algs", policy.asyncssh_encryption_algs),
            ("mac_algs", policy.asyncssh_mac_algs),
        )
        if value is not None
    }
    options = asyncssh.SSHClientConnectionOptions(config=None, **values)
    key = await asyncssh.get_server_host_key(host, port, options=options)
    if key is None:
        raise DeviceHostKeyUnknownError()
    return HostKeyMaterial(
        algorithm=key.get_algorithm(),
        public_key=key.export_public_key("openssh").decode("ascii").strip(),
        fingerprint=key.get_fingerprint("sha256"),
    )
```

Build the known-hosts line as `host key` for port 22 or `[host]:port key` otherwise. First-contact collection is the only unauthenticated probe. Candidate and registered connections load that exact line before decrypting the selected credential; OpenSSH/AsyncSSH verifies it before user authentication and maps a mismatch to `device_host_key_changed`. Missing trust raises `device_host_key_unknown`.

- [ ] **Step 5: Thread candidate confirmation through manual add/update**

Add `host_key_candidate_id: UUID | None` to candidate connection requests. `DeviceService.test_connection()` requires it when `device_id is None`; `create()` repeats the pinned test, creates `DeviceSSHHostKey` in the same transaction as `Device`, then deletes the Redis candidate. Endpoint-changing updates require a fresh candidate and replace trust only after the pinned test succeeds. Metadata-only edits preserve trust.

- [ ] **Step 6: Run tests to verify they pass**

Run the Step 2 command. Expected: PASS, with fake key probes and no network socket.

- [ ] **Step 7: Commit**

```powershell
git add backend/app backend/migrations/versions/20260806_0004_device_ssh_host_keys.py backend/tests
git commit -m "feat: pin SSH host keys per device"
```

### Task 3: Enforce the same pin in Scrapli, terminal, Compose, and lab harness

**Files:**
- Modify: `backend/app/drivers/base.py`
- Modify: `backend/app/drivers/transport.py`
- Modify: `backend/app/services/devices.py`
- Modify: `backend/app/api/terminal.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/container.py`
- Modify: `backend/tests/unit/test_drivers.py`
- Modify: `backend/tests/integration/test_terminal_vertical_slice.py`
- Modify: `backend/tests/lab/test_cisco_iosxe_lab.py`
- Modify: `.env.example`
- Modify: `deploy/compose.yml`
- Modify: `docs/lab-test-guide.md`

**Interfaces:**
- Consumes: `resolve_known_hosts(device_id, candidate_id) -> str` from Task 2.
- Produces: `ConnectionParameters.known_hosts: str`; Scrapli temporary known-hosts ownership; AsyncSSH `known_hosts=asyncssh.import_known_hosts(parameters.known_hosts)`.

- [ ] **Step 1: Write failing transport and terminal tests**

```python
def test_scrapli_uses_only_the_device_pin_and_deletes_temp_file(monkeypatch):
    transport = ScrapliTransport(parameters(known_hosts="edge.test ssh-rsa AAAAfixture"))
    transport.open()
    known_hosts_path = captured_open_options()["UserKnownHostsFile"]
    assert Path(known_hosts_path).read_text() == "edge.test ssh-rsa AAAAfixture\n"
    transport.close()
    assert not Path(known_hosts_path).exists()


def test_terminal_imports_exact_device_known_hosts(monkeypatch):
    terminal_api._open_terminal(parameters(known_hosts="edge.test ssh-rsa AAAAfixture"), pty_timeout_seconds=1)
    assert captured_asyncssh_options()["known_hosts"] is not None
```

Add tests proving missing known-hosts fails before transport construction, close is idempotent after open failure, and no raw key appears in events/logs/errors.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/unit/test_drivers.py tests/integration/test_terminal_vertical_slice.py -q`

Expected: FAIL because `ConnectionParameters` has no known-hosts material and the global toggle remains.

- [ ] **Step 3: Add the mandatory connection parameter and transport ownership**

```python
@dataclass(frozen=True, slots=True)
class ConnectionParameters:
    # existing fields unchanged
    known_hosts: str = ""
```

`DeviceService.admitted_connection()` resolves trust before decrypting the credential and fills `known_hosts`. `ScrapliTransport` writes it to a closed `NamedTemporaryFile(delete=False)` with owner-only permissions before constructing Scrapli, passes `StrictHostKeyChecking=yes` and `UserKnownHostsFile=<exact path>` to the existing request-scoped OpenSSH options, and deletes the file in idempotent `close()` plus constructor/failed-open cleanup. It never uses the user's default known-hosts file.

`terminal._open_terminal()` passes:

```python
known_hosts=asyncssh.import_known_hosts(parameters.known_hosts)
```

Remove the false branch that sets `known_hosts=None`.

- [ ] **Step 4: Remove the global weakening switches**

Delete `ssh_strict_host_key` from `Settings`, factories, `.env.example`, and Compose. Make `LAB_KNOWN_HOSTS_FILE` mandatory for the read-only lab harness and reject a missing, empty, or multi-host file before opening a socket. Keep all lab markers and `RUN_LAB_TESTS=1` requirements.

- [ ] **Step 5: Run focused and configuration tests**

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests/unit/test_config.py tests/unit/test_drivers.py tests/integration/test_terminal_vertical_slice.py -q
Set-Location ..
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.dev.yml config --quiet
```

Expected: PASS; lab test remains skipped without its explicit opt-in.

- [ ] **Step 6: Commit**

```powershell
git add backend/app backend/tests .env.example deploy/compose.yml docs/lab-test-guide.md
git commit -m "fix: enforce pinned SSH trust everywhere"
```

### Task 4: Add first-contact UI and close blocking Phase 1-2 UI states

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/network.ts`
- Modify: `frontend/src/features/inventory/DeviceForm.tsx`
- Modify: `frontend/src/features/inventory/DeviceInspector.tsx`
- Modify: `frontend/src/features/inventory/TerminalPanel.tsx`
- Modify: `frontend/src/features/topology/TopologyPage.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/tests/device-form.test.tsx`
- Modify: `frontend/tests/device-inspector.test.tsx`
- Modify: `frontend/tests/terminal-panel.test.tsx`
- Modify: `frontend/tests/topology-page.test.tsx`

**Interfaces:**
- Consumes: host-key candidate/status endpoints from Task 2 and existing TanStack Query state.
- Produces: explicit fingerprint confirmation, retry-safe terminal states, and last-good stale topology behavior.

- [ ] **Step 1: Write failing component tests**

```tsx
it('requires an explicit fingerprint confirmation before testing credentials', async () => {
  renderDeviceForm();
  await fillConnectionFields();
  await user.click(screen.getByRole('button', { name: /inspect ssh host key/i }));
  expect(await screen.findByText('SHA256:fixture')).toBeVisible();
  expect(screen.getByRole('button', { name: /test connection/i })).toBeDisabled();
  await user.click(screen.getByRole('checkbox', { name: /verified this fingerprint/i }));
  expect(screen.getByRole('button', { name: /test connection/i })).toBeEnabled();
});

it('keeps last-good topology visible when a refresh fails', async () => {
  const view = renderTopologyWithSuccessfulData();
  failNextNeighborRefresh();
  await refreshTopology(view);
  expect(screen.getByRole('img', { name: /read-only topology/i })).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent(/showing last observed topology/i);
});
```

Add assertions for changed-key recovery guidance, terminal failure focus on Retry, `aria-controls`/active panel linkage for tabs, failed diagnostic icon/text, and a 768px inspector/terminal layout source regression.

- [ ] **Step 2: Run tests to verify they fail**

Run: `Set-Location frontend; npm.cmd test -- --run tests/device-form.test.tsx tests/device-inspector.test.tsx tests/terminal-panel.test.tsx tests/topology-page.test.tsx`

Expected: FAIL on missing enrollment and stale-state UI.

- [ ] **Step 3: Implement the minimal enrollment state machine**

Use only these local form states: `uninspected`, `candidate`, `confirmed`, `testing`, `passed`, `failed`. Changing address, port, profile, vendor, or compatibility clears candidate/confirmation/test state. Display algorithm and fingerprint, never the public key. Send `host_key_candidate_id` only after the checkbox is confirmed. Map unknown/changed key codes to “Inspect and verify again”; do not expose raw backend details.

- [ ] **Step 4: Preserve useful UI on refresh/error**

In `TopologyPage`, treat a neighbor query as fatal only when it has no data. If refetch fails with previous data, keep the graph and show an alert with last-observed/stale wording and Retry. In `DeviceInspector`, render a failed job with an error icon and `role="alert"`. In `TerminalPanel`, link tab and panel IDs, restore focus to the adjacent tab after close, and keep the terminal viewport at a usable responsive minimum without redesigning the inspector.

- [ ] **Step 5: Run focused frontend verification**

Run the Step 2 command, then `npm.cmd run typecheck` and `npm.cmd run lint`.

Expected: all PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src frontend/tests
git commit -m "feat: add trusted first-contact device flow"
```

### Task 5: Verify Phase 1-2 and record conservative evidence

**Files:**
- Modify: `docs/PHASE_1_2_READINESS.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/lab-test-guide.md`
- Test: complete backend/frontend suites and Compose config

**Interfaces:**
- Consumes: Tasks 1-4 and the existing opt-in lab harness.
- Produces: automated pass record plus separate pending/passed virtual and physical metadata rows.

- [ ] **Step 1: Run routine network-free verification**

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

Expected: all checks pass; the lab suite is skipped and no target is contacted.

- [ ] **Step 2: Update automated status before any lab run**

Use the exact phrase `Automated verification passed; hardware validation pending.` Do not promote Cisco capabilities yet. Record the application commit and commands, not terminal/config output.

- [ ] **Step 3: Prepare but do not auto-run virtual acceptance**

Document an operator-run sequence using at least two explicitly authorized virtual Cisco nodes: manual add, pin, refresh, CDP/LLDP projection, terminal lifecycle, diagnostics, and stale refresh. Require exact targets and metadata-only results. This ordinary lab opt-in remains read-only.

- [ ] **Step 4: Prepare but do not auto-run physical acceptance**

Document one explicitly authorized physical Cisco run for add/pin/read/snapshot/terminal/diagnostic. State that one device cannot prove a physical CDP/LLDP link. No command, output, hostname, address, serial, configuration, screenshot, credential, or raw error may enter the record.

- [ ] **Step 5: Record only actually completed acceptance**

If no authorized run was performed, leave the result `Pending` and do not add a placeholder pass. If performed, record date, approver, browser/version, transport type, device category, application commit, requested compatibility mode, non-command validation steps, and pass/fail only.

- [ ] **Step 6: Run GitNexus change detection and commit**

```powershell
node .gitnexus/run.cjs detect-changes -r "C:\Users\User\Desktop\Coding\Terraformer" --scope compare --base-ref main
git add docs/PHASE_1_2_READINESS.md docs/IMPLEMENTATION_STATUS.md docs/CAPABILITY_MATRIX.md docs/lab-test-guide.md
git commit -m "docs: record Phase 1-2 readiness verification"
```

Expected: detected scope is limited to SSH trust, blocking Phase 1-2 UI flows, tests, and status documentation.
