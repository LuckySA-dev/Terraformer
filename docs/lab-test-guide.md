# Real-lab test guide

Real-device tests are exceptional, operator-authorized tests. They are never
part of `pytest`, CI, image build, startup health checks, or a default demo.

## Current status

An opt-in, read-only Cisco harness exists at
`backend/tests/lab/test_cisco_iosxe_lab.py`. It is skipped by default and covers
an authenticated connection plus facts, interfaces, CDP/LLDP neighbors, and
running-config reads.
No real-lab result is recorded in this repository, so every capability remains
lab-unverified until an operator runs the harness against an approved device and
records only sanitized evidence.

## Required harness contract

The `lab` test suite requires all of the following before it opens a socket:

1. a test marker excluded by default;
2. `RUN_LAB_TESTS=1` as an explicit opt-in;
3. one exact `LAB_DEVICE_HOST`—never a CIDR or hostname wildcard;
4. `LAB_EXPECTED_PLATFORM=cisco_iosxe`;
5. `LAB_DEVICE_USERNAME` and `LAB_DEVICE_PASSWORD` supplied outside Git and
   never as CLI arguments;
6. a low connection/command limit, defaulting to one; and
7. a preflight that aborts on platform mismatch or unexpected privilege.

Optional settings are `LAB_DEVICE_PORT`, `LAB_DEVICE_ENABLE_PASSWORD`, and
`LAB_SSH_STRICT_HOST_KEY`. `RUN_LAB_TESTS=1` never authorizes writes.

The harness uses one SSH session for the facts/interface/neighbor observation
batch. Connection testing and the running-config read use separate sessions.
Rejected optional CDP/LLDP commands produce no neighbor observations; a rejected
required facts/interface/config command fails the test with a typed error.

Run only after completing the checklist below:

```powershell
Set-Location backend
$env:RUN_LAB_TESTS = "1"
$env:LAB_EXPECTED_PLATFORM = "cisco_iosxe"
# Set the exact LAB_DEVICE_* values without writing them to disk or shell history.
uv run pytest tests/lab -m lab
```

## Read-only acceptance checklist

Before the test:

- Use a dedicated lab device or an explicitly approved non-production target.
- Confirm console/OOB access and identify the person who can recover the device.
- Back up the current device configuration using the lab's established process.
- Verify the target address manually and ensure no discovery range is present.
- Use a least-privilege account capable only of the required show commands when
  the platform supports it.
- Confirm that banners, hostnames, configurations, and command output may contain
  secrets and must be sanitized before retention.

During the test:

- Connect to one device with concurrency one.
- Run only the approved connection, facts, interface, CDP/LLDP neighbor, and
  running-config reads.
- Stop on an unknown prompt, privilege escalation request, timeout, malformed
  output, platform mismatch, or unexpected command.
- Do not retry authentication rapidly or fall back to a different vendor driver.

After the test:

- Confirm that device state and configuration did not change.
- Review API/worker logs and events for credential or raw-config leakage.
- Delete unsanitized temporary output according to the lab data policy.
- Record only vendor/model category, OS version, capability set, date, result,
  sanitized test reference/hash, and operator initials in the matrix.

## Write-test gate for later phases

There are no authorized write tests in phases 0–2. A future write test requires
a second explicit opt-in, exact target allowlist, per-device lock, immutable
pre-change snapshot, preview/diff, human confirmation, tested post-check, and a
platform-specific recovery plan. High-risk tests also require a maintenance
window and working console/OOB access.

Without every gate, mark the capability **Not Implemented** or lab-unverified;
do not reinterpret a successful read as evidence that a write is safe.
