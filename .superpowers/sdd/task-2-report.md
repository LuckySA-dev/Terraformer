# Task 2 Report: Password-only Scrapli Policy and Sanitized SSH Errors

## Summary

- Applied one request-scoped password-only OpenSSH option list to both Scrapli adapters.
- Kept Modern free of legacy algorithm flags; Legacy and Group1 use the exact version-1 additive policy, with Group1 in the single KEX value.
- Added one fixed SSH failure catalog with synthetic/unit coverage for TCP, negotiation, host-key verification, authentication, PTY creation, and terminal I/O mappings.
- Classified known synthetic key-exchange, host-key-type, and cipher strings as negotiation; distinct synthetic changed/unknown host-key strings map to their catalog codes, while pinned Scrapli may expose only an indeterminate host-key verification failure.
- Made open fallback errors TCP and command-path failures/timeouts terminal I/O.
- Ensured the Cisco transport closes even when `open()` or authentication fails.
- Included transport construction in the TCP translation boundary for both Cisco and Generic drivers; typed and arbitrary constructor failures are rebuilt without raw exception state, and any returned transport is closed exactly once.
- Made terminal I/O authoritative inside structured-read command error translation while preserving timeout and command-rejection semantics; real AsyncSSH terminal-path phase integration remains Task 5.
- Added the required timeout, refused, lost, name-resolution, host-key-unknown, and host-key-changed catalog codes without changing the public base-class hierarchy; distinct-code evidence is synthetic/unit-only.
- Rebuilt every translated transport error with fixed safe metadata and suppressed raw exception chains.
- Replaced exception metadata before traceback rendering and removed exception class names from worker logs.

## TDD Evidence

- RED: 11 intended failures and 47 passes after adding regressions for the prior review findings.
- GREEN: 63 focused tests passed after the centralized fix.
- Review follow-up RED/GREEN: focused regressions reproduced and fixed open cleanup, command-phase, stable-code, traceback, and worker-log failures.
- Second review RED/GREEN: constructor-failure regressions failed with raw exceptions/internal API errors, then passed for both drivers and both typed/arbitrary failures after moving construction inside the translation boundary.

## Verification

- Focused: `pytest tests/unit/test_drivers.py tests/unit/test_logging.py tests/integration/test_device_vertical_slice.py -q` — 63 passed.
- Full backend: `pytest` — 124 passed, 1 opt-in lab test skipped.
- Ruff: repository-wide `ruff check --no-cache .` passed.
- Format: all nine Task 2 production/test files pass `ruff format --check`.
- Pyright: 0 errors, 0 warnings.
- Compose: normal and development configurations both exited zero; Docker emitted only the local config-file access warning.
- `git diff --check` passed.
- No real device or external network connection was attempted.

### Review follow-up

- Full backend: 136 passed, 1 opt-in lab test skipped.
- Ruff and targeted format checks passed.
- Pyright: 0 errors, 0 warnings.
- Normal and development Compose configurations exited zero.
- `git diff --check` passed.

### Second review follow-up

- Full backend: 146 passed, 1 opt-in lab test skipped.
- Ruff and targeted format checks passed.
- Pyright: 0 errors, 0 warnings.
- Normal and development Compose configurations exited zero.
- `git diff --check` passed.

## GitNexus

- Required upstream impact was reviewed and explicitly approved: `translate_transport_error` and `CiscoIOSXEDriver._session` are CRITICAL across seven Cisco read/test flows; `redact_value` is HIGH across API, logging, and event-recording flows.
- Compare against `main`: HIGH, 22 files / 70 symbols / 10 flows, including previously committed Task 1.
- Task 2 compare against `b35eb2c`: HIGH, 8 tracked files / 39 symbols / the same 10 expected error/redaction flows. The new `ssh_errors.py` file was untracked during this comparison and is included in the staged check before commit.
- Review follow-up working tree: HIGH, 11 tracked files / 20 indexed symbols / the same 10 expected Cisco read and worker flows; no unrelated execution flow was reported.
- Second review working tree: HIGH, 8 tracked files / 30 indexed symbols / the 7 expected Cisco/Generic translation flows; no unrelated execution flow was reported.

## Commit

`fix(backend): scope legacy SSH transport`

`fix(backend): harden sanitized SSH failures`

`fix(backend): sanitize transport construction`

## Risks

- The catalog recognizes fixed strings observed in pinned-source branches plus synthetic variants; it does not claim pinned Scrapli emits every distinct code path. Pinned system transport may collapse host-key failures into the indeterminate host-key-phase fallback.
- PTY and terminal I/O mappings have catalog/unit coverage only. Integration with the real AsyncSSH terminal path is Task 5.
- Unknown open failures fail safely as TCP, while unknown structured-read command failures fail safely as terminal I/O.
- Hardware validation remains pending and separately opt-in.
- A repository-wide format check would reformat 36 pre-existing unrelated files; only Task 2 files were formatted to avoid broad churn.
