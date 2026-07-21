# Legacy SSH Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow structured Cisco and generic read-only SSH connections to negotiate with older devices while retaining modern OpenSSH algorithms as the preferred defaults.

**Architecture:** Define one immutable, narrowly scoped OpenSSH compatibility argument tuple and provide a fresh list to Scrapli's system transport for every Cisco and generic connection. Use OpenSSH's `+` syntax so the three verified legacy algorithms are appended rather than replacing modern defaults.

**Tech Stack:** Python 3.12, Scrapli system transport, OpenSSH client, pytest, Ruff, Pyright, Docker Compose

## Global Constraints

- Do not use Git commands, commits, pushes, branches, or history operations.
- Do not change `docs/network-automation-final-plan.md`.
- Do not add or expose a structured device write path.
- Do not enable `diffie-hellman-group1-sha1`, 3DES, or any unverified legacy algorithm.
- Do not change credentials, authentication retries, timeouts, strict host-key verification, or AsyncSSH Web Terminal behavior.
- Routine tests must remain network-free; the final hardware connection test is the separately authorized exact-target exception.

---

### Task 1: Structured system-transport compatibility

**Files:**
- Modify: `backend/tests/unit/test_drivers.py`
- Modify: `backend/app/drivers/transport.py`

**Interfaces:**
- Consumes: Scrapli's `transport_options={"open_cmd": list[str]}` constructor option
- Produces: Cisco and generic system transports that append the same three compatibility algorithms to OpenSSH defaults

- [x] **Step 1: Write the failing transport regression**

Add a unit test which installs fake `Scrapli` and `GenericDriver` constructors,
creates both transports, and requires each captured constructor call to contain:

```python
expected_open_cmd = [
    "-o",
    "KexAlgorithms=+diffie-hellman-group14-sha1",
    "-o",
    "HostKeyAlgorithms=+ssh-rsa",
    "-o",
    "Ciphers=+aes256-cbc",
]

assert cisco_args["transport_options"] == {"open_cmd": expected_open_cmd}
assert generic_args["transport_options"] == {"open_cmd": expected_open_cmd}
assert "diffie-hellman-group1-sha1" not in " ".join(expected_open_cmd)
assert "3des" not in " ".join(expected_open_cmd)
```

- [x] **Step 2: Run the focused test to verify RED**

Run:

```powershell
docker compose -f deploy/compose.yml exec -T api python -m pytest tests/unit/test_drivers.py::test_structured_system_transports_append_narrow_legacy_ssh_compatibility -q
```

Expected: FAIL because `transport_options` is absent from both constructor
argument dictionaries.

- [x] **Step 3: Implement the minimal shared compatibility options**

Add this private constant and fresh-copy helper to `transport.py`:

```python
_LEGACY_SSH_OPEN_CMD = (
    "-o",
    "KexAlgorithms=+diffie-hellman-group14-sha1",
    "-o",
    "HostKeyAlgorithms=+ssh-rsa",
    "-o",
    "Ciphers=+aes256-cbc",
)


def _system_transport_options() -> dict[str, list[str]]:
    return {"open_cmd": list(_LEGACY_SSH_OPEN_CMD)}
```

Pass `transport_options=_system_transport_options()` to `GenericDriver`, and
add `"transport_options": _system_transport_options()` to the Cisco device
dictionary.

- [x] **Step 4: Run the focused test to verify GREEN**

Run the Step 2 command again.

Expected: one passing test.

- [x] **Step 5: Run affected unit tests**

```powershell
docker compose -f deploy/compose.yml exec -T api python -m pytest tests/unit/test_drivers.py tests/unit/test_runtime_image.py -q
```

Expected: all selected tests pass without contacting a device.

---

### Task 2: Security documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/safety-model.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`

**Interfaces:**
- Consumes: the verified compatibility behavior from Task 1
- Produces: explicit operator documentation of the weaker fallback and conservative evidence that does not promote unsupported capabilities

- [x] **Step 1: Document the compatibility boundary**

State that structured Scrapli transports append only group14-SHA1, RSA host
key, and AES-256-CBC for legacy interoperability; modern defaults retain
priority, group1/3DES remain disabled, and strict host-key verification remains
an independent requirement.

- [x] **Step 2: Run backend static and routine verification**

```powershell
docker compose -f deploy/compose.yml exec -T api ruff format --check app/drivers/transport.py tests/unit/test_drivers.py
docker compose -f deploy/compose.yml exec -T api ruff check --no-cache .
docker compose -f deploy/compose.yml exec -T api pyright
docker compose -f deploy/compose.yml exec -T api python -m pytest
```

Expected: formatting, lint, and types pass; all routine tests pass with the
real-lab harness skipped.

- [x] **Step 3: Validate and rebuild Compose**

```powershell
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.dev.yml config --quiet
docker compose -f deploy/compose.yml up --build --detach --wait
```

Expected: both configurations are valid and the normal stack is healthy.

- [x] **Step 4: Run one authorized connection-only hardware test**

Use the selected encrypted credential profile in API memory to invoke the
Cisco connection-test path once against the exact approved endpoint. Print
only a success/failure classification and exception type; never print raw
exceptions, credentials, device output, host keys, or identifying device data.
Do not run facts, interface, neighbor, running-config, diagnostic, or write
commands.

Observed: the structured connection reached authentication, and the device
rejected the selected credential profile. No retry or alternate profile was
attempted.

- [x] **Step 5: Record conservative evidence**

Add a dated verification row to `docs/IMPLEMENTATION_STATUS.md`. Update the
capability-matrix narrative with the sanitized compatibility result, but keep
the capability `Implemented, lab unverified` because the required OS metadata
and full lab harness evidence were not collected.
