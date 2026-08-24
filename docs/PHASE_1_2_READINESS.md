# Phase 1-2 readiness ledger

Last updated: 2026-08-11

This ledger separates implementation, automated verification, virtual-lab
evidence, and physical-lab evidence. The source of truth for product intent
remains `network-automation-final-plan.md`.

## Evidence policy

**Changed 2026-08-08 by owner decision: virtual-lab evidence now satisfies
phase exit, and physical-hardware evidence is no longer a prerequisite for
starting the next phase.**

Previously a phase could not be closed without a physical-device run, which
blocked Phase 1 and Phase 2 exit indefinitely and left Phase 3 unstarted. A
GNS3 or EVE-NG run against the real driver and transport code now counts as
acceptance evidence for phase exit.

What this policy does **not** change:

- A virtual run still does not prove a *physical* platform. Per-model claims in
  `CAPABILITY_MATRIX.md` continue to require a run against that hardware, and
  virtual evidence must be recorded as virtual.
- Behaviour that virtual images cannot reproduce — notably legacy SSH
  negotiation against undersized-RSA-host-key gear — is still unproven until it
  is run against that gear. **Update 2026-08-11:** proven for Catalyst 2960 and
  2960X (see `lab-test-guide.md`). ISR 1941 specifically remains untested; the
  ISR router covered in that record is a 2911, a different platform.
- Every structured device write remains Not Implemented and Safety Level D.

## Classification

- **P0:** security, data-loss, trust-boundary, or connection blocker.
- **P1:** missing Phase 1-2 exit behavior or evidence.
- **P2:** cosmetic or post-MVP work; excluded from this closure.

`Missing implementation`, `Automated verification passed`, `Virtual lab
verified`, and `Hardware validation pending` are distinct states and must not
be collapsed.

## Conformance matrix

| Requirement | Backend | Frontend | Automated | Virtual lab | Physical lab | Priority | Status |
|---|---|---|---|---|---|---|---|
| Manual add | Implemented | Implemented | Passed | Pending | Verified (2026-08-11, 4 categories) | P1 | Automated verification passed; physical lab verified |
| Host-key trust | Mandatory exact-device pin shared by tests, reads, jobs, snapshots, and terminal | Explicit inspect/fingerprint/confirm flow | Passed | Pending | Verified (2026-08-11, 4 categories) | P0 | Automated verification passed; physical lab verified |
| Facts | Implemented | Implemented | Passed | Pending | Verified (2026-08-11, 4 categories) | P1 | Automated verification passed; physical lab verified |
| Interfaces | Implemented | Implemented | Passed | Pending | Verified (2026-08-11, 4 categories) | P1 | Automated verification passed; physical lab verified |
| Snapshot | Immutable encrypted running-config snapshot implemented | Implemented | Passed | Pending | Pending | P1 | Hardware validation pending |
| Discovery | Bounded SSH-aware discovery and approval implemented | Implemented | Passed | Pending | Not provable by one physical device | P1 | Hardware validation pending |
| CDP/LLDP | Collection and persistence implemented | Last-good graph survives refresh failure with stale/retry guidance | Passed | Pending | Verified (2026-08-11, 4 categories) | P1 | Automated verification passed; physical lab verified |
| Topology | Registered, observed, and manual-unverified projection implemented | Stale, retry, and responsive states implemented | Passed | Pending | Not provable by one physical device | P1 | Automated verification passed; hardware validation pending |
| Terminal | Bounded authenticated PTY with mandatory device pin | Linked tabs/panels, adjacent-tab focus, retry focus, and responsive viewport implemented | Passed | Pending | Verified (2026-08-11, Cisco Legacy mode, 4 categories) | P1 | Automated verification passed; physical lab verified |
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

**Automated verification passed; hardware validation pending for most
capabilities.** Backend Ruff, Pyright, 248 routine tests, frontend
type/lint/build and 131 tests, plus normal and development Compose
configuration validation passed on 2026-08-06. The single opt-in lab test
remained skipped; no device or provider connection was opened. Virtual
acceptance remains Pending.

**Physical acceptance: partially complete.** SSH connection admission,
structured facts/interface/neighbor reads, and the Direct Mode terminal
lifecycle were verified against real Cisco Catalyst 2960, 2960X, 3650, and
ISR 2911 hardware under Cisco Legacy compatibility mode on 2026-08-11 —
see the authorized record in `lab-test-guide.md`. Snapshot capture,
discovery, and diagnostics remain untested against physical hardware, and
every structured write remains Not Implemented.
