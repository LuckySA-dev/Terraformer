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

Manual USB Console has **Automated verification passed; hardware validation
pending.** Automated tests use fakes only; routine verification is network-free
and does not enumerate or open a serial adapter or connect to a device.

Device SSH terminal Direct Mode has **Automated verification passed; physical
lab verified** for Cisco Catalyst 2960, 2960X, 3650, and Cisco ISR 2911 under
Cisco Legacy compatibility mode — see the authorized record below. Other
device categories and compatibility modes remain hardware validation pending.

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

## SSH terminal hardware-validation record

Authorized by the repository owner. Metadata-only, per the schema and
prohibitions in this guide — no addresses, hostnames, credentials, commands,
terminal output, or raw errors.

| Date | Approver | Browser/version | Transport type | Device category | Application commit | Requested compatibility mode | Non-command validation steps | Pass/fail |
|---|---|---|---|---|---|---|---|---|
| 2026-08-11 | LuckySA (Owner) | Chrome 151.0.0.0 | SSH | Cisco Catalyst 2960, 2960X, 3650; Cisco ISR 2911 | 48b776d | Cisco Legacy | Connection test, structured facts/interface/neighbor read, and Direct Mode terminal open, connect, and disconnect lifecycle completed via the UI for each device category | Pass |

This record covers connection admission, structured reads, and the terminal
lifecycle only. Snapshot capture, discovery scanning, and diagnostics were not
exercised in this session and remain **Hardware validation pending**. This
record does not promote any structured-write capability; every write remains
**Not Implemented**.

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
screenshots, raw errors, recordings, identifiers, or session content. An SSH
terminal hardware result is recorded above for Cisco Catalyst 2960, 2960X, 3650,
and Cisco ISR 2911; status is **Physical lab verified (SSH terminal, Cisco Legacy
mode)** for those categories. USB Direct Mode is unaffected and remains
**Automated verification passed; hardware validation pending.**

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

## Phase 1-2 virtual acceptance gate

Status: **Pending**. Do not run this sequence without separate authorization for
at least two exact virtual Cisco nodes and the test window. Record the application
commit and metadata-only pass/fail result; never record node addresses, names,
credentials, commands, output, configuration, screenshots, or raw errors.

1. Manually add each authorized node and inspect its SSH host key.
2. Verify each displayed fingerprint out of band, confirm it, and complete the
   read-only connection test.
3. Refresh saved facts, interfaces, and CDP/LLDP observations.
4. Confirm the topology projects the saved link without creating inventory and
   keeps the last-good graph with stale guidance after an induced API test failure.
5. Validate the warning-gated terminal open, disconnect, retry, and tab lifecycle
   without retaining session content.
6. Run only the allowlisted read-only diagnostic selected in the authorization.
7. Record date, approver, browser/version, virtual transport type, device
   categories, application commit, requested compatibility modes, non-command
   validation-step descriptions, and pass/fail only.

## Phase 1-2 physical acceptance gate

Status: **Pending**. One exact authorized Cisco device may validate manual add,
host-key pinning, structured reads, immutable snapshot capture, terminal
lifecycle, and an allowlisted diagnostic. One device cannot prove a physical
CDP/LLDP link. Use the same stop conditions and metadata-only restrictions in
this guide; do not infer topology support from a single-device pass.

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

## Virtual labs (GNS3 / EVE-NG)

Added 2026-08-08, when virtual-lab evidence became sufficient for phase exit.
See `PHASE_1_2_READINESS.md` for the exact scope of that policy.

A virtual lab exercises the real drivers, transports, parsers, and safety gates.
It does **not** prove any physical platform, so record the result as virtual and
never promote a per-model claim in `CAPABILITY_MATRIX.md` from it.

### Reaching the lab from the container

The API and worker publish `host.docker.internal`, so a lab on the Docker host
is reachable at that name. Use the node's real SSH port — GNS3 and EVE-NG rarely
expose 22.

```bash
docker compose --env-file .env -f deploy/compose.yml exec worker getent hosts host.docker.internal
```

If a node is on a lab bridge the container cannot route to, add that network to
the worker rather than widening `HOST_BIND`.

### Marking a device as a lab device

Set **Device kind** to *Virtual lab* when registering. That flag does two
things, both refused for anything else:

- **Re-pin host key.** GNS3/EVE-NG nodes regenerate their SSH host key on every
  restart, which is indistinguishable from a man-in-the-middle. Lab devices can
  be re-inspected and re-pinned in place; physical devices still require delete
  and re-register, deliberately.
- **Telnet console.** Only offered for lab devices.

### Telnet consoles

Telnet is off unless the server sets `TELNET_ENABLED=true`. It is cleartext and
carries no host identity, so SSH host-key pinning does not apply and the link
can be read by anyone on the path.

Terraformer never sends the stored credential profile over Telnet — type
credentials into the session yourself, as on a console cable. Structured reads
(facts, interfaces, snapshots, diagnostics) always use SSH and are unavailable
on a Telnet-only node.

Enable it only for an isolated virtual lab, never on a management network that
carries real device credentials.

### What a virtual lab cannot prove

- Legacy SSH negotiation against real Catalyst 2960/2960-X or ISR 1941 gear.
  Virtual images present modern host keys, so they never exercise the
  undersized-RSA path that `RequiredRSASize=768` exists to handle.
- Vendor-specific CLI output from a physical platform or OS build not present in
  the virtual image.
- Timing, scale, and stability behaviour of real hardware.
