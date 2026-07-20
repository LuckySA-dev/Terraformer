# Capability matrix

Last updated: 2026-07-21
Scope: phases 0–2

## Status definitions

- **Implemented, lab unverified** — code and automated fixture/unit coverage
  exist, but the exact platform has not been recorded in a real-lab result.
- **Lab verified** — sanitized automated evidence and a dated real-lab result
  exist for the recorded vendor, model, OS version, and transport.
- **Not Implemented** — no supported product path. It must fail closed.
- **Not Applicable** — the platform cannot provide the capability by design.

“Implemented” is not the same as “Supported.” Only a dated lab evidence record
can promote a capability to **Lab verified**.

## Structured read capabilities

| Capability | Cisco IOS/IOS-XE | Juniper Junos | Generic/unknown |
|---|---|---|---|
| Explicit SSH connection test | Implemented, lab unverified | Not Implemented | Implemented, lab unverified |
| Platform identity/facts | Implemented, lab unverified | Not Implemented | Not Implemented |
| Interface inventory/state | Implemented, lab unverified | Not Implemented | Not Implemented |
| Running-config snapshot | Implemented, lab unverified | Not Implemented | Not Implemented |
| Manual-add persistence | Implemented, lab unverified | Not Implemented | Not Implemented |
| Sanitized event timeline | Implemented, lab unverified | Not Implemented | Not Implemented |
| CDP/LLDP neighbors | Implemented, lab unverified | Not Implemented | Not Implemented |
| Routing table | Implemented, lab unverified | Not Implemented | Not Implemented |
| ARP/MAC tables | Implemented, lab unverified | Not Implemented | Not Implemented |
| Bounded multi-port IPv4 SSH discovery | Implemented, lab unverified | Not Implemented | Implemented, lab unverified |
| Ping/traceroute action | Implemented, lab unverified | Not Implemented | Not Implemented |

The generic driver authenticates SSH only; facts, interfaces, and configuration
remain unsupported. Cisco read entries are deliberately lab-unverified. Before
release, link each to passing tests and record real-device acceptance below.
Discovery is vendor-neutral passive SSH identification only; it does not
authenticate, identify a platform, follow neighbors, or add inventory
automatically. Only endpoints whose received identification begins with
`SSH-` are approvable; other open TCP endpoints are informational only.
Only one discovery job may be queued or running at a time. Adding a candidate
still requires explicit approval and a successful authenticated connection test;
the resulting device and audit linkage are committed together.
The shared backend runtime includes the OpenSSH client required by the explicit
Scrapli system transport; this packaging evidence does not replace authorized
real-device validation, so SSH capabilities remain lab-unverified.
The topology canvas is a UI projection, not a new device capability. It can show
any registered device, but current observed links come only from lab-unverified
Cisco CDP/LLDP records. Dashed observed nodes never become inventory implicitly.
Cisco routing, ARP, and MAC reads use three fixed driver mappings. The structured
diagnostics API accepts no raw commands or alternate targets. Results are sanitized and capped at 64 KiB;
implementation and fixture evidence do not promote them to Lab verified.
Cisco ping/traceroute accepts one validated exact IPv4 target and renders one
bounded vendor command; hostnames, CIDR, special-use targets, and command text
fail validation.

## Direct access paths

Direct access is recorded separately because it is operator-controlled manual
access, not a structured driver read or write capability. Manual Direct Mode is
outside structured Safety Levels A–D; its warning gate does not prevent commands
from writing to or changing hardware.

| Access path | Status | Vendor scope | Safety and evidence boundary |
|---|---|---|---|
| Web SSH terminal Direct Mode | **Implemented, lab unverified** | Registered devices with an available SSH transport | Can write or otherwise change hardware; separate from drivers and structured Safety Levels A–D. Authenticated, same-origin, warning-gated, and resource-bounded; commands/output are never audit payloads. |
| Manual USB Console / USB Direct Mode | **Implemented, lab unverified** | Vendor-neutral manual serial access | Can write, modify, restart, or erase hardware; bypasses backend and structured safety controls. Automated fake-stream, privacy, lifecycle, serving-policy, type, lint, and build checks passed on 2026-07-20. Hardware validation pending; no vendor/device support claim. |

### Manual USB Console hardware evidence

No authorized hardware validation has been recorded. This table must remain
empty until an explicitly approved real-adapter session is completed. Entries
may contain only the metadata allowed by `lab-test-guide.md`; never serial-
session content.

| Date | Approver | Browser/version | Adapter type | Device category | Application version/commit | Non-command validation-step descriptions | Pass/fail outcome |
|---|---|---|---|---|---|---|---|

## Structured write capabilities

Every structured write capability is **Not Implemented**. The application must
not expose an API, worker job, driver fallback, or structured UI control that can
execute these operations. Manual Direct Mode remains the explicit path outside
this table and outside Safety Levels A–D.

| Capability | Cisco IOS/IOS-XE | Juniper Junos | Generic/unknown |
|---|---|---|---|
| Render interface description/admin state | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render access/trunk VLAN | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render SVI/IP address | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render static route | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Validate rendered commands | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Candidate/compare | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Pre-change snapshot pipeline | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Apply configuration | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Post-change checks | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Confirmed commit | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Rollback/assisted recovery | **Not Implemented** | **Not Implemented** | **Not Implemented** |

Current structured-write safety classification for every platform:
**Level D — Read-only**.

## Real-lab evidence log

No lab verification has been recorded yet.
Phase 1 release/exit remains blocked. The fixture-backed Phase 2 neighbor slice
also remains lab-unverified until an authorized read-only Cisco run supplies
sanitized evidence for this table.

| Date | Vendor/model | OS version | Capability set | Fixture/test reference | Result | Operator |
|---|---|---|---|---|---|---|
| — | — | — | — | — | Not run | — |

When adding an entry, never include an address, hostname, serial number,
credential, full configuration, or other identifying lab data. Keep the raw
evidence outside Git and attach only sanitized hashes/summaries.
