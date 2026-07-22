# Task 2 Report: Password-only Scrapli Policy and Sanitized SSH Errors

## Summary

- Applied one request-scoped password-only OpenSSH option list to both Scrapli adapters.
- Kept Modern free of legacy algorithm flags; Legacy and Group1 use the exact version-1 additive policy, with Group1 in the single KEX value.
- Added one fixed SSH failure catalog covering TCP, negotiation, host-key verification, authentication, PTY creation, and terminal I/O.
- Classified key-exchange, host-key-type, and cipher mismatches as negotiation; classified verification, changed, and unknown host keys as host-key failures.
- Made open fallback errors TCP and command-path failures/timeouts terminal I/O.
- Ensured the Cisco transport closes even when `open()` or authentication fails.
- Made terminal I/O authoritative for typed and Scrapli command-path connection failures while preserving timeout and command-rejection semantics.
- Split collapsed transport errors into the required timeout, refused, lost, name-resolution, host-key-unknown, and host-key-changed stable codes without changing the public base-class hierarchy.
- Rebuilt every translated transport error with fixed safe metadata and suppressed raw exception chains.
- Replaced exception metadata before traceback rendering and removed exception class names from worker logs.

## TDD Evidence

- RED: 11 intended failures and 47 passes after adding regressions for the prior review findings.
- GREEN: 63 focused tests passed after the centralized fix.
- Review follow-up RED/GREEN: focused regressions reproduced and fixed open cleanup, command-phase, stable-code, traceback, and worker-log failures.

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

## GitNexus

- Required upstream impact was reviewed and explicitly approved: `translate_transport_error` and `CiscoIOSXEDriver._session` are CRITICAL across seven Cisco read/test flows; `redact_value` is HIGH across API, logging, and event-recording flows.
- Compare against `main`: HIGH, 22 files / 70 symbols / 10 flows, including previously committed Task 1.
- Task 2 compare against `b35eb2c`: HIGH, 8 tracked files / 39 symbols / the same 10 expected error/redaction flows. The new `ssh_errors.py` file was untracked during this comparison and is included in the staged check before commit.
- Review follow-up working tree: HIGH, 11 tracked files / 20 indexed symbols / the same 10 expected Cisco read and worker flows; no unrelated execution flow was reported.

## Commit

`fix(backend): scope legacy SSH transport`

`fix(backend): harden sanitized SSH failures`

## Risks

- Classification intentionally recognizes the fixed messages emitted by the pinned Scrapli system transport; unknown open failures fail safely as TCP, while unknown command failures fail safely as terminal I/O.
- Hardware validation remains pending and separately opt-in.
- A repository-wide format check would reformat 36 pre-existing unrelated files; only Task 2 files were formatted to avoid broad churn.
