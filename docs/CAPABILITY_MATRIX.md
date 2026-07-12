# Capability matrix

Last updated: 2026-07-12
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

## Read capabilities

| Capability | Cisco IOS/IOS-XE | Juniper Junos | Generic/unknown |
|---|---|---|---|
| Explicit SSH connection test | Implemented, lab unverified | Not Implemented | Implemented, lab unverified |
| Platform identity/facts | Implemented, lab unverified | Not Implemented | Not Implemented |
| Interface inventory/state | Implemented, lab unverified | Not Implemented | Not Implemented |
| Running-config snapshot | Implemented, lab unverified | Not Implemented | Not Implemented |
| Manual-add persistence | Implemented, lab unverified | Not Implemented | Not Implemented |
| Sanitized event timeline | Implemented, lab unverified | Not Implemented | Not Implemented |
| CDP/LLDP neighbors | Implemented, lab unverified | Not Implemented | Not Implemented |
| Routing table | Not Implemented | Not Implemented | Not Implemented |
| ARP/MAC tables | Not Implemented | Not Implemented | Not Implemented |
| Bounded IPv4 SSH discovery | Implemented, lab unverified | Not Implemented | Implemented, lab unverified |
| Web terminal | Not Implemented | Not Implemented | Not Implemented |
| Ping/traceroute action | Not Implemented | Not Implemented | Not Implemented |

The generic driver authenticates SSH only; facts, interfaces, and configuration
remain unsupported. Cisco read entries are deliberately lab-unverified. Before
release, link each to passing tests and record real-device acceptance below.
Discovery is vendor-neutral TCP port evidence only; it does not identify a
platform, authenticate, follow neighbors, or add inventory automatically.
Only one discovery job may be queued or running at a time. Adding a candidate
still requires explicit approval and a successful authenticated connection test;
the resulting device and audit linkage are committed together.

## Write capabilities

Every write is **Not Implemented**. The application must not expose an API,
worker job, driver fallback, or UI control that can execute these operations.

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

Current write safety classification for every platform: **Level D — Read-only**.

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
