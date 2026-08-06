# Task 9 Report: Final verification and conservative status

## Verification

Run in the run2 worktree at `59d76ef`, with no lab opt-ins:

```text
backend/.venv/Scripts/python.exe -m ruff check --no-cache .
backend/.venv/Scripts/pyright.exe
backend/.venv/Scripts/python.exe -m pytest
frontend/npm.cmd run typecheck
frontend/npm.cmd run lint
frontend/npm.cmd test
frontend/npm.cmd run build
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.yml -f deploy/compose.dev.yml config --quiet
```

Results: Ruff passed; Pyright reported 0 errors/0 warnings; backend reported
236 passed/1 skipped (the explicit opt-in lab test); frontend typecheck and lint
passed, Vitest reported 12 files/124 tests passed, and the production build
passed. Both Compose configuration commands exited 0 without starting Compose;
each emitted only an unreadable host Docker config warning. `npm` was blocked by
the local PowerShell execution policy, so the equivalent Windows `npm.cmd`
launcher was used.

Focused routine regressions also passed:

```text
backend/.venv/Scripts/python.exe -m pytest tests/integration/test_terminal_vertical_slice.py tests/integration/test_device_vertical_slice.py tests/unit/test_connection_gate.py tests/unit/test_ssh_compatibility.py tests/unit/test_logging.py tests/unit/test_queue.py
frontend/npm.cmd test -- --run tests/terminal-panel.test.tsx tests/terminal-input-policy.test.ts tests/usb-console-dialog.test.tsx tests/usb-serial-transport.test.ts tests/serving-policy.test.ts
```

Results: backend 113 passed; frontend 5 files/85 tests passed. These cover raw
markers, queue arguments, Redis key hashing, terminal WebSocket messages,
storage/network exclusion for USB Direct Mode, and xterm privileged APIs.

## Diff and exclusion review

The `main...59d76ef` scan reviewed every match for `password`, private-key/raw
markers, documentation-range addresses, browser storage, telemetry, and
terminal logging. Matches were request-scoped policy, sanitizer assertions,
fake credentials/raw markers, documentation-range test data, and intentional
no-storage guards; no credential, terminal-content, or telemetry sink was
found. `git diff --check main...HEAD` passed.

The exclusion scan found no Telnet/FTP, automatic legacy fallback, algorithm
discovery, graph configuration, structured writes, RBAC facade, active-session
registry, generated commands, vendor templates, or Phase 3 implementation.
The only `fallback` and peer-offer matches were the documented fail-closed
policy, sanitizer fixtures, and tests. The final plan and approved design are
unchanged.

## Documentation and scope

Updated only `IMPLEMENTATION_STATUS.md`, `CAPABILITY_MATRIX.md`,
`lab-test-guide.md`, `safety-model.md`, and `user-guide.md`, plus this report.
They record policy version 1 and its exact algorithms, all server kill switches
and limits, modern-default/no-fallback behavior, unchanged host-key policy,
Direct Mode hardware risk, network-free routine verification, and the exact
status wording **Automated verification passed; hardware validation pending**.
Cisco legacy SSH terminal and topology claims remain lab-unverified. The
hardware record schema is metadata-only.

### GitNexus change detection

The controller's `ALL_TOOLS` confirms that the GitNexus MCP
`detect_changes({scope: "compare", base_ref: "main"})` tool is unavailable in
this environment. The repository-supported existing-index CLI invokes the same
local change-detection backend without analysis or refresh, so this exact
equivalent was run from the run2 worktree:

```text
node .gitnexus\run.cjs detect-changes --scope compare --base-ref main --repo 'C:\Users\User\Desktop\Coding\Terraformer\.worktrees\cisco-legacy-ssh-terminal-run2'
```

It exited 0 and reported 68 changed files, 591 changed symbols, 87 affected
processes, and Critical aggregate risk. Manual inspection found the affected
scope limited to the approved accumulated Task 1–8 device/discovery/terminal
backend paths, terminal UI and transport paths, migrations, configuration,
tests, and documentation. The listed flows were the expected connection-test,
device create/update, discovery approval, terminal lifecycle/input, and cleanup
flows; no unexpected execution flow or Task 9 feature-code change was found.
The Critical rating therefore describes the already reviewed whole feature
branch against `main`, not this documentation-only task. The earlier staged
Task 9 scope reported 6 documentation/report files, 15 documentation symbols,
0 flows, and Low risk. The unavailable MCP call remains an environment
limitation and is not claimed as run. No GitNexus analysis or index refresh was
run.

## Commit and concerns

Commit: `docs: record legacy SSH verification status`.

No feature code, preview, network/device/lab activity, or Compose start was
performed. Existing untracked SDD review artifacts and the pre-existing
`progress.md` change remain excluded from the commit.

## Fix round 1

- Added the implemented SSH-open, PTY/shell, permit-TTL, and WebSocket-frame
  limits to `safety-model.md` with exact configuration names and defaults.
- Re-ran the existing-index GitNexus CLI compare command recorded above; it
  exited 0 with the same expected accumulated scope and no unexpected flow.
- `.venv\Scripts\python.exe -m pytest tests/unit/test_config.py` passed all 6
  tests; `docker compose -f deploy/compose.yml config --quiet` exited 0 without
  starting services and emitted only the known host Docker-config permission
  warning; `git diff --check` passed.
- The final plan and approved design remain unchanged. No feature code, network,
  device, lab, Compose-start, GitNexus-analysis, or index-refresh action ran.
- Commit: `docs: record terminal verification limits`.
