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

Manual USB Console and device SSH terminal Direct Mode have
**Automated verification passed; hardware validation pending.** Automated tests
use fakes only; routine verification is network-free and does not enumerate or
open a serial adapter or connect to a device.

## Manual USB Console hardware-validation gate

Do not start any real-adapter session without explicit approval for the exact
hardware and test window. The approver must understand that USB Direct Mode is
not read-only and that typed or pasted commands can modify, restart, or erase
the attached device. Use same-machine Chrome or Edge over HTTPS or localhost,
verify `Permissions-Policy: serial=(self)`, establish console/OOB recovery, and
stop on any unexpected prompt or device behavior.

An authorized validation record may contain only these metadata fields:

| Date | Approver | Browser/version | Adapter/transport type | Device category | Application commit | Requested compatibility mode | Non-command validation-step descriptions | Pass/fail outcome |
|---|---|---|---|---|---|---|---|---|

No authorized hardware result has been recorded. Do not add a placeholder that
could be mistaken for a completed test.

The record must never contain terminal output, commands, credentials,
configuration, addresses, hostnames, serial numbers, adapter or device
identifiers, raw errors or exceptions, screenshots, recordings, or session
content. Non-command validation-step descriptions may describe only the UI or
lifecycle behavior checked; they must not reproduce device interaction. Do not
attach or link prohibited content as evidence. Until an explicitly authorized
session is completed and this metadata-only record is added, retain the status
**Automated verification passed; hardware validation pending.**

## SSH terminal hardware-validation gate

Device SSH terminal validation requires separate operator approval for one exact
authorized target and test window. The operator must acknowledge that Direct Mode
commands can change, restart, or erase the device, and must confirm working
console/OOB access plus a documented recovery owner and procedure before connecting.

Mandatory host-key verification is required for this validation. Pre-enroll and
verify the authorized target's host key through the established lab process; never
automatically trust, replace, or ignore an unknown or changed key. Stop immediately
on a host-key mismatch, unexpected prompt or privilege, target mismatch, repeated
authentication failure, timeout, connection instability, or unexpected device
behavior. Do not retry in another compatibility mode unless that mode and attempt
were separately approved for the same window.

The authorized record uses only the existing metadata-only evidence schema above:
date, approver, browser/version, adapter or transport type, device category,
application commit, requested compatibility mode, non-command validation-step
descriptions, and pass/fail outcome. The same prohibitions apply: no addresses,
hostnames, serial numbers, credentials, commands, terminal output, configuration,
screenshots, raw errors, recordings, identifiers, or session content. No SSH terminal
hardware result is recorded; status remains **Automated verification passed; hardware
validation pending.**

## Required harness contract

The `lab` test suite requires all of the following before it opens a socket:

1. a test marker excluded by default;
2. `RUN_LAB_TESTS=1` as an explicit opt-in;
3. one exact `LAB_DEVICE_HOST`—never a CIDR or hostname wildcard;
4. `LAB_EXPECTED_PLATFORM=cisco_iosxe`;
5. `LAB_DEVICE_USERNAME` and `LAB_DEVICE_PASSWORD` supplied outside Git and
   never as CLI arguments;
6. `LAB_KNOWN_HOSTS_FILE` containing exactly the selected endpoint and its
   explicitly verified public host key;
7. a low connection/command limit, defaulting to one; and
8. a preflight that aborts on platform mismatch or unexpected privilege.

Optional settings are `LAB_DEVICE_PORT` and `LAB_DEVICE_ENABLE_PASSWORD`.
There is no relaxed host-key mode. `RUN_LAB_TESTS=1` never authorizes structured
or Direct Mode writes.

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

There are no authorized structured-write tests in phases 0–2. A future
structured-write test requires a second explicit opt-in, exact target allowlist,
per-device lock, immutable pre-change snapshot, preview/diff, human confirmation,
tested post-check, and a platform-specific recovery plan. High-risk tests also
require a maintenance window and working console/OOB access. Manual USB Console
hardware validation has the separate explicit authorization and metadata-only
record gate above; it does not promote structured write support.

Without every gate, mark the capability **Not Implemented** or lab-unverified;
do not reinterpret a successful read as evidence that a write is safe.
