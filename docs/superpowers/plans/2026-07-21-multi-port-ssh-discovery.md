# Multi-Port SSH-Aware Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Probe up to four operator-selected TCP ports in an authorized IPv4 CIDR and permit approval only for endpoints which identify as SSH.

**Architecture:** Extend the existing bounded socket discovery instead of adding a scanner dependency. Classify passive TCP results into SSH candidates and informational non-SSH endpoints, retain the existing explicit approval gate, and expose the small port list in the current dialog.

**Tech Stack:** Python stdlib sockets/thread pool, Pydantic, FastAPI/RQ, React 19, TypeScript, TanStack Query, Vitest

## Global Constraints

- CIDR remains mandatory; ports do not identify hosts without an authorized address range.
- Maximum 64 IPv4 addresses, four unique ports, and 256 endpoint probes per job.
- Discovery sends no credentials, commands, protocol negotiation, or authentication attempts.
- Banner bytes, socket exceptions, credentials, and session content are never persisted or returned.
- FTP, Telnet, HTTP, and unknown open endpoints are never approvable as SSH devices.
- No Nmap, Netmiko SSHDetect, FTP client, Telnet client, or automatic device creation.
- Leave `docs/network-automation-final-plan.md` unchanged.

---

### Task 1: Define and enforce the multi-port discovery contract

**Files:**
- Modify: `backend/tests/unit/test_discovery.py`
- Modify: `backend/tests/integration/test_discovery_vertical_slice.py`
- Modify: `backend/app/schemas/discovery.py`
- Modify: `backend/app/services/discovery.py`

**Interfaces:**
- Consumes: `DiscoveryRequest(cidr, ports, concurrency, connect_timeout_seconds, probe_delay_ms)`.
- Produces: `DiscoveryResult` with `ports`, endpoint-count `scanned_count`, SSH `candidates`, and non-SSH `open_endpoints`.

- [ ] **Step 1: Add failing request validation tests**

Add to `backend/tests/unit/test_discovery.py`:

```python
def test_discovery_normalizes_ports_and_bounds_endpoint_count() -> None:
    request = DiscoveryRequest(cidr="192.0.2.0/26", ports=[22, 2222, 22, 23])

    assert request.ports == [22, 2222, 23]
    assert len(list(request.network().hosts())) * len(request.ports) <= 256


@pytest.mark.parametrize(
    "ports",
    [[], [22, 23, 2222, 2200, 2022], [0], [65_536]],
)
def test_discovery_rejects_unsafe_port_lists(ports: list[int]) -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(cidr="192.0.2.0/30", ports=ports)
```

- [ ] **Step 2: Replace the single-port fake probe test with classification coverage**

Use this fake signature and expected result in the existing concurrency test:

```python
def probe(address: str, port: int, timeout: float) -> str | None:
    assert port in {22, 23}
    assert timeout == 0.25
    with lock:
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
    sleep(0.05)
    with lock:
        state["active"] -= 1
    if (address, port) == ("192.0.2.2", 22):
        return "ssh"
    if (address, port) == ("192.0.2.5", 23):
        return "open_tcp"
    return None
```

Construct with `ports=[22, 23]` and assert:

```python
assert result["ports"] == [22, 23]
assert result["scanned_count"] == 12
assert result["concurrency"] == 2
assert state["peak"] == 2
assert result["candidates"] == [
    {"management_address": "192.0.2.2", "port": 22},
]
assert result["open_endpoints"] == [
    {"management_address": "192.0.2.5", "port": 23},
]
```

- [ ] **Step 3: Add failing passive-banner tests**

Import the service module and add a socket fake which can return partial reads:

```python
from collections.abc import Iterator

from app.services import discovery as discovery_service


class BannerSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks: Iterator[bytes] = iter(chunks)

    def __enter__(self) -> "BannerSocket":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, _timeout: float) -> None:
        pass

    def recv(self, size: int) -> bytes:
        assert 0 < size <= 512
        return next(self._chunks, b"")

    def send(self, _data: bytes) -> int:
        raise AssertionError("discovery must not send bytes")

    def sendall(self, _data: bytes) -> None:
        raise AssertionError("discovery must not send bytes")


def probe_with_chunks(monkeypatch, chunks: list[bytes]) -> str | None:
    connection = BannerSocket(chunks)
    monkeypatch.setattr(
        discovery_service.socket,
        "create_connection",
        lambda *_args, **_kwargs: connection,
    )
    return discovery_service.tcp_service_probe("192.0.2.1", 22, 0.25)


def test_passive_probe_identifies_split_ssh_banner(monkeypatch) -> None:
    assert probe_with_chunks(monkeypatch, [b"SS", b"H-2.0-OpenSSH_fixture\r\n"]) == "ssh"


def test_passive_probe_keeps_non_ssh_banner_informational(monkeypatch) -> None:
    assert probe_with_chunks(monkeypatch, [b"220 fixture FTP service\r\n"]) == "open_tcp"
    assert probe_with_chunks(monkeypatch, [b""]) == "open_tcp"
```

No fake exposes terminal content to the result; its `send` methods fail if production code attempts to write.

- [ ] **Step 4: Update the integration fixture before implementation**

Change the submitted request to `"ports": [22, 23]`. Return:

```python
{
    "cidr": "192.0.2.0/30",
    "ports": [22, 23],
    "scanned_count": 4,
    "concurrency": min(2, connection_limit),
    "candidates": [{"management_address": "192.0.2.1", "port": 22}],
    "open_endpoints": [{"management_address": "192.0.2.1", "port": 23}],
}
```

Before approving the SSH candidate, POST the same address on port 23 and assert status 409 and zero devices. Keep the existing port-22 approval assertions.

- [ ] **Step 5: Run discovery tests and verify RED**

Run:

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/unit/test_discovery.py tests/integration/test_discovery_vertical_slice.py -q
```

Expected: failures because the schema accepts only `port`, probes return Boolean, and results have no `open_endpoints`.

- [ ] **Step 6: Implement the request and result schema**

In `backend/app/schemas/discovery.py`, add `Annotated` and define:

```python
from typing import Annotated

Port = Annotated[int, Field(ge=1, le=65_535)]


class DiscoveryRequest(APIModel):
    cidr: str
    ports: list[Port] = Field(default_factory=lambda: [22], min_length=1, max_length=4)
    concurrency: int = Field(default=4, ge=1, le=10)
    connect_timeout_seconds: float = Field(default=0.5, gt=0, le=5)
    probe_delay_ms: int = Field(default=50, ge=10, le=1_000)

    @field_validator("ports", mode="before")
    @classmethod
    def normalize_ports(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[object] = []
        for port in value:
            if port not in normalized:
                normalized.append(port)
        return normalized
```

Keep the current CIDR validator and `network()` method. Replace `DiscoveryResult.port` with:

```python
ports: list[int]
```

and add:

```python
open_endpoints: list[DiscoveryCandidate]
```

- [ ] **Step 7: Implement the passive classifier and endpoint loop**

In `backend/app/services/discovery.py`, replace the Boolean probe type and function with:

```python
from time import monotonic
from typing import Literal

ProbeStatus = Literal["ssh", "open_tcp"]
PortProbe = Callable[[str, int, float], ProbeStatus | None]


def tcp_service_probe(address: str, port: int, timeout: float) -> ProbeStatus | None:
    deadline = monotonic() + timeout
    try:
        with socket.create_connection((address, port), timeout=timeout) as connection:
            banner = bytearray()
            try:
                while len(banner) < 512:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        return "open_tcp"
                    connection.settimeout(remaining)
                    chunk = connection.recv(512 - len(banner))
                    if not chunk:
                        break
                    banner.extend(chunk)
                    if any(line.startswith(b"SSH-") for line in banner.splitlines()):
                        return "ssh"
            except TimeoutError:
                return "open_tcp"
    except OSError:
        return None
    return "open_tcp"
```

Flatten `(address, port)` combinations, submit `tcp_service_probe`, and construct:

```python
results = [(address, port, future.result()) for address, port, future in futures]
candidates = [
    DiscoveryCandidate(management_address=address, port=port)
    for address, port, result in results
    if result == "ssh"
]
open_endpoints = [
    DiscoveryCandidate(management_address=address, port=port)
    for address, port, result in results
    if result == "open_tcp"
]
return DiscoveryResult(
    cidr=request.cidr,
    ports=request.ports,
    scanned_count=len(addresses) * len(request.ports),
    concurrency=concurrency,
    candidates=candidates,
    open_endpoints=open_endpoints,
).model_dump(mode="json")
```

- [ ] **Step 8: Run discovery tests and verify GREEN**

Run:

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/unit/test_discovery.py tests/integration/test_discovery_vertical_slice.py -q
```

Expected: all selected tests pass and no network target is contacted.

- [ ] **Step 9: Commit the backend discovery contract**

```text
git add backend/app/schemas/discovery.py backend/app/services/discovery.py backend/tests/unit/test_discovery.py backend/tests/integration/test_discovery_vertical_slice.py
git commit -m "feat(discovery): identify SSH across selected ports"
```

### Task 2: Expose selected ports and non-SSH results in the existing dialog

**Files:**
- Modify: `frontend/tests/discovery-dialog.test.tsx`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/features/inventory/DiscoveryDialog.tsx`

**Interfaces:**
- Consumes: backend `ports`, `candidates`, and `open_endpoints` result fields.
- Produces: comma-separated port input; approval remains available only for `candidates`.

- [ ] **Step 1: Update the dialog test for multiple ports**

Add `ports: [22, 23]` and `open_endpoints: [{ management_address: '192.0.2.1', port: 23 }]` to the succeeded result, clear the default value before typing `22, 23` into a textbox named `TCP ports`, and expect:

```typescript
const portsInput = screen.getByRole('textbox', { name: 'TCP ports' });
await user.clear(portsInput);
await user.type(portsInput, '22, 23');
```

```typescript
expect(api.startDiscovery).toHaveBeenCalledWith({
  cidr: '192.0.2.0/30',
  ports: [22, 23],
  concurrency: 4,
  connect_timeout_seconds: 0.5,
  probe_delay_ms: 50,
});
expect(await screen.findByText('192.0.2.1:22')).toBeVisible();
expect(screen.getByText(/192\.0\.2\.1:23/)).toBeVisible();
expect(screen.getAllByRole('button', { name: /review and approve/i })).toHaveLength(1);
```

Add one test which clears the default, enters `22,23,2222,2200,2022`, submits, expects an inline alert containing `1 to 4`, and asserts `api.startDiscovery` was not called.

- [ ] **Step 2: Run the focused frontend test and verify RED**

Run: `cd frontend && npm.cmd test -- --run tests/discovery-dialog.test.tsx`

Expected: failures because the port input and new result fields do not exist.

- [ ] **Step 3: Update API types**

Replace `DiscoveryInput.port` and `DiscoveryResult.port` with:

```typescript
ports: number[];
```

Add to `DiscoveryResult`:

```typescript
open_endpoints: DiscoveryCandidate[];
```

- [ ] **Step 4: Add the bounded native port input**

Add state:

```typescript
const [portInput, setPortInput] = useState('22');
const [portError, setPortError] = useState<string>();
```

At form submission, parse and validate before `start.mutate`:

```typescript
const ports = [...new Set(portInput.split(',').map((value) => Number(value.trim())))];
if (
  ports.length === 0
  || ports.length > 4
  || ports.some((port) => !Number.isInteger(port) || port < 1 || port > 65_535)
) {
  setPortError('Enter 1 to 4 TCP ports between 1 and 65535.');
  return;
}
setPortError(undefined);
start.mutate({
  cidr: cidr.trim(),
  ports,
  concurrency: 4,
  connect_timeout_seconds: 0.5,
  probe_delay_ms: 50,
});
```

Render beside the CIDR field:

```tsx
<InputField
  label="TCP ports"
  value={portInput}
  onChange={(event) => setPortInput(event.target.value)}
  error={portError}
  required
  spellCheck={false}
  hint="Comma-separated; maximum 4 ports and 256 endpoint checks"
/>
```

Update warning/loading copy from SSH port 22 to selected TCP ports and SSH identification.

- [ ] **Step 5: Render non-SSH open endpoints without an action**

Below SSH candidates, render:

```tsx
{!result?.open_endpoints.length ? null : (
  <InlineNotice tone="warning" title="Open endpoints not identified as SSH">
    {result.open_endpoints
      .map((endpoint) => `${endpoint.management_address}:${String(endpoint.port)}`)
      .join(', ')}
    {' — informational only; these endpoints cannot be approved.'}
  </InlineNotice>
)}
```

- [ ] **Step 6: Run the focused test and verify GREEN**

Run: `cd frontend && npm.cmd test -- --run tests/discovery-dialog.test.tsx`

Expected: all discovery dialog tests pass.

- [ ] **Step 7: Commit the UI slice**

```text
git add frontend/src/types/api.ts frontend/src/features/inventory/DiscoveryDialog.tsx frontend/tests/discovery-dialog.test.tsx
git commit -m "feat(ui): select bounded discovery ports"
```

### Task 3: Verify and record the discovery change

**Files:**
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`

**Interfaces:**
- Consumes: completed backend and frontend slices.
- Produces: conservative automated evidence; hardware validation remains pending.

- [ ] **Step 1: Run complete backend verification**

```text
cd backend
.venv/Scripts/python.exe -m ruff check --no-cache .
.venv/Scripts/pyright.exe
.venv/Scripts/python.exe -m pytest
```

Expected: lint/types pass, all routine tests pass, and the real-lab test remains skipped.

- [ ] **Step 2: Run complete frontend verification**

Run: `cd frontend && npm.cmd run verify`

Expected: TypeScript, ESLint, Vitest, and the Vite production build pass.

- [ ] **Step 3: Validate both Compose configurations**

```text
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.yml -f deploy/compose.dev.yml config --quiet
```

Expected: both commands exit 0.

- [ ] **Step 4: Update status without promoting support**

Change the Phase 2 row and checklist wording from one-port TCP discovery to bounded
multi-port SSH-aware discovery. Record that automated verification passed and hardware
validation remains pending. In `docs/CAPABILITY_MATRIX.md`, state that only SSH-identified
candidates are approvable and open non-SSH endpoints are informational.

- [ ] **Step 5: Check final change impact**

Run:

```text
C:/Users/User/AppData/Roaming/npm/gitnexus.cmd detect-changes --scope compare --base-ref main --repo Terraformer-backend-ssh --branch fix/backend-ssh-discovery
```

Expected: SSH runtime, discovery request/service/approval flow, inventory discovery dialog, tests, and status documents only.

- [ ] **Step 6: Commit documentation**

```text
git add docs/IMPLEMENTATION_STATUS.md docs/CAPABILITY_MATRIX.md docs/superpowers/plans/2026-07-21-backend-ssh-runtime-hardening.md docs/superpowers/plans/2026-07-21-multi-port-ssh-discovery.md
git commit -m "docs: record SSH-aware discovery verification"
```
