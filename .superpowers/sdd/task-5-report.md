# Task 5 implementation report

## Delivered scope

- Rebuilt the device terminal boundary around the shared SSH compatibility policy and Redis connection gate.
- Applies compatibility mode immediately before each AsyncSSH connection, keeps authentication password-only, preserves strict host-key verification by default, and makes the documented relaxed-host-key mode independent of compatibility mode.
- Requires direct-mode and group1 risk acknowledgement before admission, acquires the shared gate before credential decryption, and reports authentication success or failure only for the authentication phase.
- Adds independent connection and PTY timeouts, typed sanitized connection/shell failures, input/output/idle/session limits, sequential output backpressure, and one idempotent cleanup path for relays, PTY/connection, WebSocket, and gate permit.
- Records only bounded allowlisted audit metadata. Terminal input/output, credentials, targets, algorithm details, and raw transport exceptions are not persisted or logged.
- Removed the process-local terminal session counter from `ApplicationContainer`; cross-replica admission now uses the shared gate.
- The API command already included `--ws-max-size 8192` at the Task 5 starting commit, so no Compose edit was necessary.

## GitNexus impact review

- Pre-edit upstream impact classified `terminal`, `_open_terminal`, `_connection_parameters`, and the removed process-local reserve/release methods as LOW. `ApplicationContainer` was MEDIUM with 5 direct importers and 15 total affected symbols. No pre-edit check was HIGH or CRITICAL.
- Required comparison against `main` reports CRITICAL for the accumulated Tasks 1–5 branch: 43 files, 161 changed symbols, and 35 affected processes. That broad result includes the already-delivered Tasks 1–4 and is not the isolated Task 5 risk.
- Staged-only detection isolates Task 5 to 3 files, 41 changed symbols, 9 affected processes, and HIGH risk. Every affected process belongs to the expected terminal authentication/parameter or relay read/write/resize/error boundary; no unrelated production flow is present.
- GitNexus's CLI did not forward the linked-worktree override and initially failed Windows safe-directory canonicalization. Detection was completed through its local backend with the explicit registered repository and worktree paths plus command-scoped safe-directory values; no index rewrite or re-analysis was performed.

## TDD evidence

- RED: the focused terminal suite initially reported 25 failed and 3 passed. Failures covered missing independent PTY handling, sanitized failure mapping, direct/group1 acknowledgement, shared-gate admission ordering and cleanup, bounded relay behavior, and authentication accounting.
- GREEN: `pytest tests/integration/test_terminal_vertical_slice.py -q` reports 33 passed.
- Tests use fake AsyncSSH connections, fake WebSockets, fake gate state, and documentation-range addresses only. Deterministic thread events verify cancellation and disconnect cleanup without sleeps or network access.

## Final verification

- `python -m pytest`: 228 passed, 1 skipped. The skip is the separately opted-in read-only lab test; no device or network target was contacted.
- `python -m ruff check --no-cache .`: passed.
- `ruff format --check app/api/terminal.py app/container.py tests/integration/test_terminal_vertical_slice.py`: passed (3 files already formatted).
- Full-repository `ruff format --check .` retains the existing baseline of 36 unrelated files that would be reformatted; none were changed by this task.
- `pyright`: 0 errors, 0 warnings.
- Production and development `docker compose ... config --quiet`: passed. Docker emitted only local user-config permission warnings.
- `git diff --check`: passed.
- Security-sensitive diff scan found only request-scoped password use, fake test credentials/raw-error markers, the session-cookie lookup, and documentation-range address `192.0.2.10`; it found no logging or persistence sink.

The immutable final plan was not changed. No device write capability was added.

## Review follow-up

- AsyncSSH 2.23.1 connection options now explicitly set `gss_kex=False` and `disable_trivial_auth=True`. A real `SSHClientConnectionOptions` construction verifies password is the only enabled user-authentication method while strict host-key behavior and additive compatibility algorithms remain unchanged.
- Central logging setup now disables the `asyncssh` logger exactly like `scrapli`: handlers are cleared, a `NullHandler` is installed, and propagation is disabled. A real child-logger probe confirms arbitrary target, username, peer-algorithm, and raw-marker text emits nothing.
- PTY creation cancellation and unexpected exceptions close and await the AsyncSSH connection before propagating. Integration coverage proves the Redis permit remains held until connection close completes.
- Gate acquisition is shielded from caller cancellation. When cancellation wins a blocked thread acquisition, the code awaits its result, releases a late permit exactly once under shielded cleanup, and then re-raises cancellation before credential decryption or SSH open.
- Terminal failures now reference shared `SanitizedSSHFailure` objects instead of copying their phase, retryability, and recommended action. Pinned exception-shape coverage maps an untrusted/changed AsyncSSH host key, name-resolution failure, refused connection, and generic connection failure without exposing raw details.
- Review RED: the focused terminal/logging suite reported 12 failed and 35 passed across the five blockers. A follow-up pinned AsyncSSH host-key-message regression independently failed 1 of 4 cases before its mapping fix.
- Review GREEN: the focused terminal/logging suite reports 46 passed; the mapping probe reports 4 passed; the standalone raw AsyncSSH logging probe reports 1 passed.
- Fresh full verification reports 236 passed and 1 opt-in lab test skipped, full Ruff lint passed, the 4 changed Python files are formatted, Pyright reports 0 errors and 0 warnings, both Compose configurations validate, and `git diff --check` passes.
- GitNexus comparison from `0b289c9` reports HIGH for 4 changed files, 17 indexed symbols, and 9 affected terminal parameter/relay processes. No unrelated production process is included.
