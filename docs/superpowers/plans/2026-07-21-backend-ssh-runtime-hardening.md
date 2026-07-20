# Backend SSH Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Scrapli system transport runnable in the backend image and return sanitized, accurate transport errors.

**Architecture:** Keep `DeviceDriver` and `NetworkTransport` unchanged. Satisfy Scrapli's existing system-transport runtime contract in Docker, make the transport selection explicit, and harden the one shared error translator used by Cisco and generic SSH reads.

**Tech Stack:** Python 3.12, FastAPI, Scrapli 2025.1.30, Debian bookworm-slim, pytest, Ruff, Pyright, Docker Compose

## Global Constraints

- Do not contact a network device; the opt-in lab test remains skipped.
- Do not log, return, persist, or transmit credentials, raw exceptions, commands, or device output.
- Do not add Netmiko, NAPALM, Nornir, parser libraries, or an automatic transport fallback.
- Preserve all structured device writes as Not Implemented / Safety Level D.
- Leave `docs/network-automation-final-plan.md` unchanged.

---

### Task 1: Install the existing transport's runtime dependency

**Files:**
- Create: `backend/tests/unit/test_runtime_image.py`
- Modify: `backend/Dockerfile`

**Interfaces:**
- Consumes: Scrapli `transport="system"`, which invokes the `ssh` executable.
- Produces: A runtime image where `ssh -V` exits successfully.

- [ ] **Step 1: Write the failing runtime-image source check**

```python
from pathlib import Path


def test_runtime_image_installs_openssh_client() -> None:
    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text(encoding="utf-8")
    runtime_stage = dockerfile.split("AS runtime", maxsplit=1)[1]

    assert "openssh-client" in runtime_stage
    assert "--no-install-recommends" in runtime_stage
    assert "rm -rf /var/lib/apt/lists/*" in runtime_stage
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_runtime_image.py -q`

Expected: FAIL because the runtime stage does not contain `openssh-client`.

- [ ] **Step 3: Install only OpenSSH client in the runtime stage**

Insert before `USER app` and combine account creation in the same layer:

```dockerfile
RUN apt-get update \
    && apt-get install --yes --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app app
```

Remove the old standalone `RUN groupadd ...` line.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_runtime_image.py -q`

Expected: `1 passed`.

- [ ] **Step 5: Commit the runtime dependency**

```text
git add backend/Dockerfile backend/tests/unit/test_runtime_image.py
git commit -m "fix(backend): install Scrapli SSH runtime"
```

### Task 2: Make the Scrapli transport contract explicit

**Files:**
- Modify: `backend/tests/unit/test_drivers.py`
- Modify: `backend/app/drivers/transport.py`

**Interfaces:**
- Consumes: `ConnectionParameters` and the existing `strict_host_key` factory option.
- Produces: Both Scrapli constructors receive `transport="system"` without changing callers.

- [ ] **Step 1: Extend both existing constructor tests**

Add this assertion to `test_connection_and_command_timeouts_are_wired_independently`:

```python
assert captured["transport"] == "system"
```

Add the same assertion to `test_generic_transport_is_authenticated_but_vendor_neutral`:

```python
assert captured["transport"] == "system"
```

- [ ] **Step 2: Run both tests and verify RED**

Run:

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/unit/test_drivers.py::test_connection_and_command_timeouts_are_wired_independently tests/unit/test_drivers.py::test_generic_transport_is_authenticated_but_vendor_neutral -q
```

Expected: both fail with a missing `transport` key.

- [ ] **Step 3: Pass the explicit transport twice**

Add to the Cisco device dictionary and the generic constructor:

```python
"transport": "system",
```

```python
transport="system",
```

- [ ] **Step 4: Run the driver unit tests and verify GREEN**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_drivers.py -q`

Expected: all driver tests pass.

- [ ] **Step 5: Commit the explicit contract**

```text
git add backend/app/drivers/transport.py backend/tests/unit/test_drivers.py
git commit -m "refactor(backend): declare Scrapli system transport"
```

### Task 3: Harden the shared transport-error translator

**Files:**
- Modify: `backend/tests/unit/test_drivers.py`
- Modify: `backend/tests/integration/test_device_vertical_slice.py`
- Modify: `backend/tests/unit/test_logging.py`
- Modify: `backend/app/core/logging.py`
- Modify: `backend/app/drivers/generic_readonly.py`
- Modify: `backend/app/jobs/tasks.py`

**Interfaces:**
- Consumes: `translate_transport_error(exc: Exception) -> Exception` and Scrapli's published exceptions.
- Produces: Existing application error classes with sanitized default messages; no caller changes.

- [ ] **Step 1: Replace synthetic class-name tests with real Scrapli exceptions**

Import:

```python
from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliTimeout,
    ScrapliTransportPluginError,
    ScrapliValueError,
)

from app.core.errors import (
    ConfigurationError,
    DriverAuthenticationError,
    DriverConnectionError,
    DriverTimeoutError,
)
```

Replace `test_transport_errors_are_typed` with:

```python
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ScrapliTimeout("raw-timeout-marker"), DriverTimeoutError),
        (ScrapliAuthenticationFailed("Permission denied raw-auth-marker"), DriverAuthenticationError),
        (ScrapliAuthenticationFailed("Timed out connecting raw-timeout-marker"), DriverTimeoutError),
        (ScrapliAuthenticationFailed("Host key verification failed raw-key-marker"), DriverConnectionError),
        (ScrapliAuthenticationFailed("No matching key exchange raw-kex-marker"), DriverConnectionError),
        (ScrapliValueError("ssh executable not found raw-runtime-marker"), ConfigurationError),
        (ScrapliTransportPluginError("raw-plugin-marker"), ConfigurationError),
        (RuntimeError("raw-unknown-marker"), DriverConnectionError),
    ],
)
def test_transport_errors_are_typed_and_sanitized(
    error: Exception,
    expected: type[Exception],
) -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}, open_error=error))

    with pytest.raises(expected) as captured:
        driver.test_connection(parameters())

    assert "raw-" not in str(captured.value)
```

- [ ] **Step 2: Run the test and verify RED**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_drivers.py::test_transport_errors_are_typed_and_sanitized -q`

Expected: at least host-key and runtime cases fail under the existing class-name substring mapping.

- [ ] **Step 3: Implement typed, sanitized mapping in the shared function**

Add the imports and replace the function body with:

```python
from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliModuleNotFound,
    ScrapliTimeout,
    ScrapliTransportPluginError,
    ScrapliValueError,
)

from app.core.errors import ConfigurationError

_CREDENTIAL_REJECTION_MARKERS = ("permission denied", "password prompt")
_TIMEOUT_MARKERS = ("timed out connecting",)


def translate_transport_error(exc: Exception) -> Exception:
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, ScrapliTimeout):
        return DriverTimeoutError()
    if isinstance(exc, ScrapliAuthenticationFailed):
        message = str(exc).lower()
        if any(marker in message for marker in _TIMEOUT_MARKERS):
            return DriverTimeoutError()
        if any(marker in message for marker in _CREDENTIAL_REJECTION_MARKERS):
            return DriverAuthenticationError()
        return DriverConnectionError()
    if isinstance(
        exc,
        (ScrapliValueError, ScrapliModuleNotFound, ScrapliTransportPluginError),
    ):
        return ConfigurationError()
    return DriverConnectionError()
```

- [ ] **Step 4: Run all driver tests and verify GREEN**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_drivers.py -q`

Expected: all driver tests pass with no raw marker in failures.

- [ ] **Step 5: Add a failing regression for raw worker exception logs**

Add imports for `pytest`, `ScrapliAuthenticationFailed`, and
`DriverAuthenticationError` to `backend/tests/integration/test_device_vertical_slice.py`,
then add:

```python
def test_background_driver_failure_does_not_log_raw_exception(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    session_factory: sessionmaker[Session],
    transport_factory,
    monkeypatch,
    capsys,
) -> None:
    created = authenticated_client.post(
        "/api/devices",
        json=_device_payload(str(credential_profile["id"])),
    )
    job = authenticated_client.post(f"/api/devices/{created.json()['id']}/refresh")
    transport_factory.command_error = ScrapliAuthenticationFailed(
        "Permission denied raw-worker-marker"
    )
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)

    with pytest.raises(DriverAuthenticationError):
        tasks.execute_job(job.json()["id"])

    assert "raw-worker-marker" not in capsys.readouterr().out
    with session_factory() as session:
        stored = session.get(Job, UUID(job.json()["id"]))
        assert stored is not None
        assert stored.error_code == "device_authentication_failed"
        assert stored.error_message == "The device rejected the credential profile"
```

Run:

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/integration/test_device_vertical_slice.py::test_background_driver_failure_does_not_log_raw_exception -q
```

Expected: FAIL because `logger.exception()` renders the chained raw cause.

- [ ] **Step 6: Stop persistent worker and RQ tracebacks for sanitized job failures**

Replace the worker exception log with metadata only:

```python
logger.error(
    "device_job_failed",
    job_id=job_id,
    error_code=code,
    error_type=type(exc).__name__,
)
```

Raise a fresh exception with the sanitized type/message `from None` after the
database failure record is committed. The regression formats the caught
exception using the same `traceback.format_exception` operation used by RQ and
asserts that the raw cause is absent.

Configure the `scrapli` logger namespace with a `NullHandler` and
`propagate=False`. A logging regression clears any preinstalled handler first
and asserts that a CRITICAL raw marker reaches neither stdout nor stderr.

Run:

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/integration/test_device_vertical_slice.py::test_background_driver_failure_does_not_log_raw_exception -q
```

Expected: PASS; the job record contains only the sanitized error code/message.

- [ ] **Step 7: Run critical-path integration regressions**

Run:

```text
cd backend
.venv/Scripts/python.exe -m pytest tests/integration/test_device_vertical_slice.py tests/integration/test_diagnostics_vertical_slice.py -q
```

Expected: all selected integration tests pass without a device connection.

- [ ] **Step 8: Commit the shared error fix**

```text
git add backend/app/core/logging.py backend/app/drivers/generic_readonly.py backend/app/jobs/tasks.py backend/tests/unit/test_drivers.py backend/tests/unit/test_logging.py backend/tests/integration/test_device_vertical_slice.py
git commit -m "fix(backend): sanitize Scrapli transport errors"
```

### Task 4: Verify the runtime and record conservative status

**Files:**
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Retain: `docs/research/2026-07-21-backend-network-tooling-evaluation.md`
- Retain: `docs/superpowers/specs/2026-07-21-backend-ssh-and-discovery-hardening-design.md`

**Interfaces:**
- Consumes: the rebuilt shared backend image.
- Produces: automated evidence only; Cisco remains lab-unverified.

- [ ] **Step 1: Run backend verification**

```text
cd backend
.venv/Scripts/python.exe -m ruff check --no-cache .
.venv/Scripts/pyright.exe
.venv/Scripts/python.exe -m pytest
```

Expected: Ruff passes, Pyright reports 0 errors, 65+ tests pass, and the opt-in lab test is skipped.

- [ ] **Step 2: Validate Compose without starting a device session**

Run:

```text
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.yml -f deploy/compose.dev.yml config --quiet
```

Expected: both commands exit 0.

- [ ] **Step 3: Build and smoke-test the backend image when Docker is available**

```text
docker build --tag terraformer-backend:ssh-runtime-test backend
docker run --rm --entrypoint ssh terraformer-backend:ssh-runtime-test -V
```

Expected: the image builds and OpenSSH prints its version with exit code 0. If Docker is unavailable, record container verification as pending; do not claim it passed.

- [ ] **Step 4: Update the status ledgers**

Append a dated verification row to `docs/IMPLEMENTATION_STATUS.md` containing only commands and results. Keep Phase 1 and Cisco connection entries `lab unverified`.

Add one sentence below the structured capability table in `docs/CAPABILITY_MATRIX.md`:

```markdown
The shared backend runtime includes the OpenSSH client required by the explicit
Scrapli system transport; this packaging evidence does not replace authorized
real-device validation, so SSH capabilities remain lab-unverified.
```

- [ ] **Step 5: Check change impact before commit**

Run:

```text
C:/Users/User/AppData/Roaming/npm/gitnexus.cmd detect-changes --scope compare --base-ref main --repo Terraformer-backend-ssh --branch fix/backend-ssh-discovery
```

Expected: only the backend transport/runtime paths, their tests, and documentation are reported.

- [ ] **Step 6: Commit documentation and verification evidence**

```text
git add docs/IMPLEMENTATION_STATUS.md docs/CAPABILITY_MATRIX.md docs/research/2026-07-21-backend-network-tooling-evaluation.md docs/superpowers/specs/2026-07-21-backend-ssh-and-discovery-hardening-design.md
git commit -m "docs: record backend SSH runtime hardening"
```
