# Phase 1-2 readiness ledger

Last updated: 2026-08-06

This ledger separates implementation, automated verification, virtual-lab
evidence, and physical-lab evidence. A passing fixture or virtual test never
promotes a physical-device capability. The source of truth for product intent
remains `network-automation-final-plan.md`.

## Classification

- **P0:** security, data-loss, trust-boundary, or connection blocker.
- **P1:** missing Phase 1-2 exit behavior or evidence.
- **P2:** cosmetic or post-MVP work; excluded from this closure.

`Missing implementation`, `Automated verification passed`, and `Hardware
validation pending` are distinct states and must not be collapsed.

## Conformance matrix

| Requirement | Backend | Frontend | Automated | Virtual lab | Physical lab | Priority | Status |
|---|---|---|---|---|---|---|---|
| Manual add | Implemented | Implemented | Passed | Pending | Pending | P1 | Hardware validation pending |
| Host-key trust | Mandatory exact-device pin shared by tests, reads, jobs, snapshots, and terminal | Explicit inspect/fingerprint/confirm flow | Passed | Pending | Pending | P0 | Automated verification passed; hardware validation pending |
| Facts | Implemented | Implemented | Passed | Pending | Pending | P1 | Hardware validation pending |
| Interfaces | Implemented | Implemented | Passed | Pending | Pending | P1 | Hardware validation pending |
| Snapshot | Immutable encrypted running-config snapshot implemented | Implemented | Passed | Pending | Pending | P1 | Hardware validation pending |
| Discovery | Bounded SSH-aware discovery and approval implemented | Implemented | Passed | Pending | Not provable by one physical device | P1 | Hardware validation pending |
| CDP/LLDP | Collection and persistence implemented | Last-good graph survives refresh failure with stale/retry guidance | Passed | Pending | Not provable by one physical device | P1 | Automated verification passed; hardware validation pending |
| Topology | Registered, observed, and manual-unverified projection implemented | Stale, retry, and responsive states implemented | Passed | Pending | Not provable by one physical device | P1 | Automated verification passed; hardware validation pending |
| Terminal | Bounded authenticated PTY with mandatory device pin | Linked tabs/panels, adjacent-tab focus, retry focus, and responsive viewport implemented | Passed | Pending | Pending | P1 | Automated verification passed; hardware validation pending |
| Diagnostics | Allowlisted RQ jobs implemented | Failed jobs have error icon, text, and alert semantics | Passed | Pending | Pending | P1 | Automated verification passed; hardware validation pending |

## Fixed closure scope

1. Replace the global SSH host-key toggle with explicit first-contact
   fingerprint confirmation and a per-device pin shared by connection tests,
   structured reads, and the SSH terminal.
2. Preserve last-good topology during refresh failure and expose stale/retry
   guidance.
3. Close blocking terminal tab focus, responsive viewport, and diagnostic
   failure-state gaps.
4. Re-run network-free verification, then prepare separately authorized virtual
   multi-node and physical single-device acceptance.

Cosmetic redesign, animation, Phase 0 backup/restore, structured writes, and
hardware claims not supported by the available topology are P2 or outside this
closure.

## Evidence boundary

Automated verification must not open a device or provider connection. Lab
acceptance requires a separate exact-target authorization and records only date,
approver, browser/version, transport type, device category, application commit,
requested compatibility mode, non-command validation steps, and pass/fail. It
never records addresses, hostnames, serial numbers, credentials, commands,
terminal output, configuration, screenshots, raw errors, or session content.

## Current result

**Automated verification passed; hardware validation pending.** Backend Ruff,
Pyright, 248 routine tests, frontend type/lint/build and 131 tests, plus normal
and development Compose configuration validation passed on 2026-08-06. The
single opt-in lab test remained skipped; no device or provider connection was
opened. Virtual and physical acceptance remain Pending.
