# Implementation status

Last updated: 2026-08-06
Current delivery target: phases 0–2

This is the status ledger, not a roadmap. Product intent and future scope remain
in `network-automation-final-plan.md`.

The requirement-level Phase 1-2 closure audit is tracked in
`PHASE_1_2_READINESS.md`. It distinguishes missing implementation, automated
verification, virtual-lab evidence, and physical-lab evidence.

## Status meanings

- **Implemented** — code exists and required automated verification passes.
- **Lab unverified** — automated checks pass, but real-device acceptance has not
  been recorded.
- **Not Implemented** — no supported product path.

## Phase summary

| Phase | Status | Delivered boundary | Exit-criterion result |
|---|---|---|---|
| 0 — Repository and safety foundation | Implemented | Local Compose stack, file-secret bootstrap, PostgreSQL/Redis/RQ, migrations, health, authentication, encrypted credentials, sanitized logging, tests and operator docs | Passed automated and local-runtime acceptance |
| 1 — First real device | Implemented; exit blocked — lab unverified | Exact-target manual add, capability-gated Cisco IOS/IOS-XE structured read-only connection/facts/interfaces/running-config snapshots, generic authenticated connection test, jobs/events and operator UI | Automated acceptance passed; phase exit requires an authorized real Cisco structured read-only run, which is not recorded |
| 2 — Topology and terminal | Implemented; exit blocked — lab unverified | Bounded multi-port SSH-aware discovery/approval; CDP/LLDP topology with saved layouts and unverified manual links; allowlisted show/ping/traceroute diagnostics; guarded Web PTY Direct Mode | Automated acceptance passed; phase exit still requires an authorized lab topology plus terminal/diagnostic evidence |
| 3 — Safe configuration MVP | Not Implemented | None; all structured writes remain Level D | Not started because Phase 2 lab exit is not yet proven |
| 4–8 | Not Implemented | None | Future phases |

## Phase 0 checklist

| Item | Status | Evidence |
|---|---|---|
| Safe non-secret `.env.example` | Implemented | Contains paths and non-secret settings only |
| Idempotent local secret initialization | Implemented | `deploy/init-secrets.py`; valid files retained and invalid files rejected |
| One-command bootstrap wrappers | Implemented | `deploy/start.ps1` and `deploy/start.sh` |
| PostgreSQL 17 and Redis 7 persistence | Implemented | Compose services and named volumes; runtime health passed |
| Shared API/worker image and one-shot migration gate | Implemented | Clean image build; migrate exited 0 before API/worker startup |
| API, worker, database, queue and web health | Implemented | All five long-running services reported healthy |
| Master-password setup and encrypted credentials | Implemented | Argon2id and AES-GCM tests plus API/UI integration coverage |
| Sanitized structured logging and typed errors | Implemented | Unit/integration tests cover fixed SSH failure codes/phases, traceback replacement before rendering, and worker records without exception names or raw values |
| Default loopback exposure | Implemented | Only web is published, on `127.0.0.1:8080` |
| No model runtime in base deployment | Implemented | No model/AI service exists in Compose |

## Phase 1 checklist

| Item | Status | Evidence |
|---|---|---|
| Cisco IOS/IOS-XE connection test | Implemented; lab unverified | Password-only Scrapli system-transport policy, sanitized phase-specific error mapping, capability/transport unit tests, and opt-in lab harness |
| Exact-target manual add | Implemented; lab unverified | API/service/UI vertical-slice tests; no CIDR discovery path |
| Mandatory per-device SSH host-key trust | Implemented; lab unverified | **Automated verification passed; hardware validation pending.** First contact returns algorithm/fingerprint only; explicit confirmation produces an exact endpoint pin shared by connection tests, reads, jobs, snapshots, and terminal |
| Facts collection | Implemented; lab unverified | Sanitized golden fixtures and parser/driver tests |
| Interface inventory/state | Implemented; lab unverified | Sanitized golden fixtures and API/UI tests |
| Immutable running-config snapshot | Implemented; lab unverified | Compress-then-encrypt, tamper, traversal and no-overwrite tests; PostgreSQL immutable trigger present |
| Read-only device inspector and event timeline | Implemented | React component and API tests; visual QA against running Compose stack |
| Generic/unknown platform | Implemented; lab unverified | Authenticated SSH connection test only; other capabilities fail closed |
| Fortinet FortiOS connection test and terminal | Implemented; lab unverified | Authenticated SSH connection test and Direct Mode terminal only; structured reads and writes fail closed |
| Every structured device write capability | **Not Implemented** | Required current safety boundary; manual Direct Mode is outside structured Safety Levels A–D and can write/change hardware |

## Phase 2 checklist

| Item | Status | Evidence |
|---|---|---|
| Cisco CDP/LLDP neighbor collection | Implemented; lab unverified | Sanitized parser fixtures, capability/error tests, refresh job integration |
| Neighbor persistence and API | Implemented; lab unverified | Migration `20260712_0002`, replacement semantics, typed authenticated endpoint |
| Observed-neighbor inspector | Implemented | React component test; records labeled `OBSERVED` |
| Bounded multi-port IPv4 SSH discovery and approve flow | Implemented; lab unverified | Maximum 64 addresses, 4 unique operator-selected ports and 256 passive endpoint checks; only SSH-identified endpoints are approvable; open non-SSH endpoints are informational; bounded concurrency/timeout/rate, one active scan at a time, atomic approval audit, fake-probe tests, no credentials or automatic inventory creation |
| Read-only topology canvas and links | Implemented; lab unverified | Cytoscape projection of registered devices and saved CDP/LLDP records; browser-local node positions; manual/30/60-second view refresh; interface-pair labels; browser-local manual links always labeled `UNVERIFIED` |
| Allowlisted Cisco diagnostics | Implemented; lab unverified | Typed routing/ARP/MAC plus bounded exact-IPv4 ping/traceroute actions; fixed driver mappings; RQ execution; sanitized 64 KiB cap and local download; injection/timeout/unsupported tests |
| Web SSH terminal | Implemented; lab unverified | **Automated verification passed; hardware validation pending.** AsyncSSH PTY over authenticated same-origin WebSocket; mandatory exact-device host-key pin; password-only, device-scoped `compatibility_policy_version = 2` (`modern` default; no fallback; per-device explicit selection for `cisco_legacy`, `cisco_legacy_group1`, and `very_old_ssh`); explicit Direct Mode confirmation before credential decrypt/connect; no command/output recording |
| Manual USB Console / USB Direct Mode | Implemented; lab unverified | **Automated verification passed; hardware validation pending.** Same-machine Chrome/Edge Web Serial path with secure-context and `serial=(self)` checks, per-session authorization warning, settings, multiline confirmation, bounded writes, five-second cleanup, fresh-session reopen, and fake-stream privacy/lifecycle coverage; no real adapter was contacted |

## Verification record

| Date | Scope | Command/evidence | Result |
|---|---|---|---|
| 2026-07-11 | Backend lint | `python -m ruff check --no-cache .` | Passed |
| 2026-07-11 | Backend types | `pyright` | 0 errors, 0 warnings |
| 2026-07-11 | Backend tests | `python -m pytest` | 32 passed, 1 opt-in lab test skipped; 3.12 s |
| 2026-07-11 | Frontend full verification | `npm run verify` | TypeScript and ESLint passed; 13 tests passed; Vite production build passed (1,919 modules) |
| 2026-07-11 | Dependency audit | `npm audit` | 0 vulnerabilities |
| 2026-07-11 | Container build/start | `docker compose --env-file .env.example -f deploy/compose.yml up --build --detach --wait --force-recreate` | Backend/web images built; migrate exited 0; API, worker, PostgreSQL, Redis and web healthy |
| 2026-07-11 | Database schema | Query through API container | Alembic `20260711_0001`; trigger `config_snapshots_immutable` |
| 2026-07-11 | Runtime API | `GET /api/health`, `/api/setup`, `/api/devices` | Dependencies all `ok`; unconfigured first run; protected route returned typed 401 |
| 2026-07-11 | Browser QA | In-app browser at `http://127.0.0.1:8080/` | First-run security page rendered with expected controls and no disconnected state |
| 2026-07-11 | Secret/worktree review | Git status/ignore inspection and sanitized fixture review | Secret directories, virtualenv, dependencies and build output ignored; fixtures use documentation-only test data |
| 2026-07-12 | Git and backend re-verification | `git status --short`; Ruff; Pyright; `python -m pytest` | Git clean; lint/types passed; 32 passed, 1 opt-in lab test skipped |
| 2026-07-12 | Frontend re-verification | `npm run verify` | TypeScript, ESLint and 13 tests passed; Vite production build passed |
| 2026-07-12 | Compose and migration re-verification | Normal/dev `docker compose config --quiet`; `alembic current`; `alembic heads`; `alembic check` | Configs valid; all services healthy; DB at `20260711_0001` head; no model drift |
| 2026-07-12 | Phase 2 neighbor slice | Ruff; Pyright; `python -m pytest`; frontend type/lint/tests | Static checks passed; backend 38 passed/1 lab skipped; frontend 15 passed |
| 2026-07-12 | Phase 2 container/migration | Compose rebuild and health; `alembic current/heads/check` | Images built; all services healthy; DB at `20260712_0002` head; no model drift |
| 2026-07-12 | Core real-lab readiness refactor | Fixture-backed refresh and transport tests | Refresh observations use one SSH session; optional CDP/LLDP rejection preserves facts/interfaces; required command rejection remains typed |
| 2026-07-12 | Phase 2 bounded discovery slice | Ruff; Pyright; backend/frontend tests; production build; Compose health | Backend 47 passed/1 lab skipped; frontend 17 passed; maximum 64 addresses; no real probe in tests; all services healthy |
| 2026-07-12 | Phase 2 discovery safety refactor | Targeted Ruff format; Ruff; Pyright; `python -m pytest`; frontend type/lint/tests; Vite temp-output build; Compose config/image build; `alembic current/heads/check` | Backend 47 passed/1 lab skipped; frontend 18 passed; API/UI prevent overlapping scans; approval creation and audit share one transaction; both images built; DB at `20260712_0002` with no drift |
| 2026-07-12 | Phase 2 observed topology slice | Frontend type/lint/tests; Vite production build; `npm audit`; Compose config; isolated web image build/recreate/health | 22 frontend tests passed; 0 vulnerabilities; Cytoscape lazy chunk 443 kB; web healthy on `127.0.0.1:8080`; no device network operation |
| 2026-07-12 | Phase 2 allowlisted diagnostics slice | Targeted Ruff format; Ruff; Pyright; backend/frontend tests; Vite build; Compose config | Backend 54 passed/1 lab skipped; frontend 24 passed; production build passed; normal/dev Compose configs valid; Docker image build blocked by Codex approval usage limit; no real device command run |
| 2026-07-12 | Phase 2 completion slice | Targeted Ruff format; Ruff; Pyright; backend/frontend tests; Vite/Docker builds; normal/dev Compose config; Alembic current/heads/check; runtime health | Backend 65 passed/1 opt-in lab skipped; frontend 29 passed; API/web images built; all five services healthy; DB at `20260712_0002` with no drift; no real-device operation run |
| 2026-07-20 | Manual USB Console frontend verification | `npm.cmd run verify`; `npm.cmd audit`; focused `npm.cmd test -- --run tests/serving-policy.test.ts` | TypeScript and ESLint passed; 11 test files / 90 tests passed; Vite production build passed (1,934 modules, existing large-chunk warning); serving-policy test 2 passed; audit found 0 vulnerabilities |
| 2026-07-20 | Routine backend regression | `.venv\Scripts\python.exe -m ruff check --no-cache .`; `.venv\Scripts\pyright.exe`; `.venv\Scripts\python.exe -m pytest` | Ruff passed; Pyright 0 errors, 0 warnings; 65 passed and 1 explicitly opt-in real-lab test skipped; no device opt-in supplied |
| 2026-07-20 | Local secret and Compose runtime | `python deploy/init-secrets.py` twice; both Compose `config --quiet` commands; `docker compose -f deploy/compose.yml up --build --detach --wait`; API-container `alembic current`, `heads`, and `check`; `docker compose -f deploy/compose.yml down` without `-v` | Worktree secrets were created, then retained byte-for-byte without printing values. Isolated runtime images built; PostgreSQL, Redis, migrate, API, worker, and web completed/healthy as applicable; database was at `20260712_0002` head with no model drift; cleanup left zero containers and no listener while preserving volumes |
| 2026-07-20 | Serving policy | Static Nginx/Vite regression plus hidden loopback Vite and production Compose `HEAD /` checks | Development and production responses contained `camera=(), microphone=(), geolocation=(), serial=(self)`; both local launchers/listeners and the Compose stack were explicitly stopped and confirmed absent |
| 2026-07-20 | Manual USB Console UI polish | CSS-source regression; USB component regression; `npm.cmd run verify` | Scoped light-surface and privacy-note declarations passed source and component checks; 12 files / 91 tests, type check, lint, and production build passed; browser visual validation remains pending; no hardware contacted |
| 2026-07-21 | SSH runtime hardening and multi-port SSH-aware discovery | Backend Ruff, Pyright and `python -m pytest`; frontend `npm.cmd run verify`; normal/dev Compose `config --quiet`; focused fake transport/banner, logging, RQ-formatting and approval regressions | **Automated verification passed; hardware validation pending.** Backend 85 passed/1 opt-in lab skipped; frontend 12 files/92 tests plus typecheck, lint and production build passed; both Compose configs valid. Docker image smoke-test remains pending because the local Docker Desktop daemon was unavailable; no device connection or real network probe was performed. |
| 2026-07-22 | Cisco legacy SSH transport and sanitized failure hardening | Targeted Ruff format; repository Ruff; Pyright; `python -m pytest`; normal/dev Compose `config --quiet`; fake Scrapli/constructor/open/command/logging/worker regressions | **Automated verification passed; hardware validation pending.** Backend 146 passed/1 opt-in lab skipped; Pyright 0 errors/0 warnings; both Compose configs valid. Password-only OpenSSH options are request-scoped; constructor/open failures are sanitized and returned transports close exactly once; stable phase-specific errors and worker records contain no raw exception content or class names. No device connection or external network operation was performed. |
| 2026-08-06 | Cisco legacy SSH terminal final routine verification | Backend Ruff, Pyright, complete pytest; frontend typecheck, lint, complete Vitest, production build; focused secret/persistence/network/xterm regressions; normal/dev Compose `config --quiet` | **Automated verification passed; hardware validation pending.** Backend 236 passed/1 opt-in lab skipped; frontend 12 files/124 tests passed; focused backend 113 and frontend 85 tests passed. No lab opt-in, device connection, external network operation, preview, or Compose start was performed. |
| 2026-08-06 | Phase 1-2 readiness closure (`e8a474e`, `348f636`) | Backend Ruff, Pyright and complete pytest; frontend `npm run verify`; normal and merged development Compose `config --quiet` | **Automated verification passed; hardware validation pending.** Backend 248 passed/1 opt-in lab skipped; frontend 12 files/131 tests plus typecheck, lint and production build passed; both Compose configurations valid. No lab opt-in, device connection, external network operation, preview, or Compose start was performed. |
| 2026-08-06 | Very Old SSHv2 capability and Fortinet driver integration | Backend Ruff, Pyright, complete pytest; frontend typecheck, lint, complete Vitest, production build; database migration `20260806_0005_very_old_ssh` | **Automated verification passed; hardware validation pending.** Backend 285 passed/1 opt-in lab skipped; frontend 12 files/134 tests passed. All 3 kill-switches enforced for very_old_ssh; password-only and exact-device pinning preserved. No device connection or external network operation was performed. |
| 2026-08-08 | Read-only Batfish analysis: opt-in real-container parse test | `docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.analysis.yml --profile analysis up --detach --wait`; `RUN_ANALYSIS_TESTS=1 BATFISH_HOST=127.0.0.1 BATFISH_PORT=<mapped> .venv/Scripts/python.exe -m pytest tests/analysis -v`; full backend `pytest`; Ruff; Pyright | Batfish parsed this application's real sanitized Cisco IOS-XE fixture (`tests/fixtures/cisco_iosxe/running_config.txt`, 1 device, 1 interface) with zero parse warnings; `interfaceProperties`, `traceroute` (disposition `DELIVERED_TO_SUBNET`, correct per-hop action from a real multi-step trace) and `testFilters` (correct `PERMIT`/`DENY` verdict and matched ACL line, confirmed against both a permit and a deny result) were exercised manually against the same container and matched expectations; two real client bugs found and fixed this way (`port_v2` must be a `Session` constructor argument, not set post-construction; `interfaceProperties` rejects a `properties=` filter argument in this Batfish release). Validation reached **1 device**. The 200-device `analysis_max_devices` bound is enforced in code but is not evidence of capacity at that scale — see design spec §8.4. Backend suite unaffected: 315 passed/6 pre-existing unrelated failures/1 opt-in lab skipped; Ruff and Pyright clean. |

## Security decisions verified

- Device credentials are encrypted server-side with AES-GCM and are never
  returned by credential APIs.
- The local administrator password is stored only as an Argon2id verifier.
- Snapshots are compressed before encryption, use authenticated context, reject
  tampering/path traversal and cannot be overwritten in storage or PostgreSQL.
- State-changing browser requests enforce trusted-origin checks; session cookies
  are HttpOnly and SameSite strict.
- Structured driver operations are capability-gated. Current code contains no
  supported configuration apply or model-execution path. Manual terminal access
  is isolated as warning-gated Direct Mode and does not log commands or output.
  Discovery candidates and neighbor records do not create topology nodes or
  links automatically.

## Known gaps

- No real-device lab result is recorded. Phase 1 exit remains blocked; the user
  explicitly directed fixture-only Phase 2 work, so Cisco reads remain **lab
  unverified**.
- Mandatory host-key pinning and its explicit UI enrollment flow have automated
  coverage only. No unknown or changed key is trusted automatically, and no
  authorized metadata-only virtual or physical acceptance record exists yet.
- The backend Dockerfile now includes the OpenSSH client required by Scrapli's
  explicit system transport, but the rebuilt-image `ssh -V` smoke-test is
  pending because Docker Desktop was unavailable during this verification.
- Manual USB Console automated verification passed, but hardware validation is
  pending. It remains lab-unverified, and no device/vendor support is inferred
  from browser, fake-stream, serving-policy, or local Compose evidence. Manual
  Direct Mode is outside structured Safety Levels A–D and can write/change
  hardware.
- No structured write capability is implemented.
- Backup/restore acceptance is not implemented in phases 0–2.
- Broader LAN exposure has not been hardened or tested; normal deployment stays
  loopback-only.
- Phase 2 automated implementation is complete, but its exit cannot be promoted
  without an authorized real-lab topology plus terminal/diagnostic run. Phase 3
  remains intentionally unstarted until that evidence exists.
- Direct Mode is an explicit operator escape hatch and can change a device. It
  has no parser, approval plan, rollback guarantee, or recording by design.
- Cisco legacy SSH terminal and topology claims remain lab-unverified. The
  approved compatibility-policy version, kill switches, and resource limits
  have automated coverage only; no real hardware result is recorded.
- Read-only configuration analysis is optional and off by default. It is
  Cisco IOS/IOS-XE only; Fortinet and generic devices are reported as
  exclusions. Its device and findings limits are enforced bounds that protect
  the host, not evidence of capacity: the recorded validation reached a small
  number of nodes, and everything above that is unverified. Measured capacity
  belongs to Phase 7.
- No analysis query or parse timeout is enforced. The design spec §8.2/§8.3
  called for one, but `pybatfish` drives a module-level `requests.Session`
  that exposes no timeout knob, so the setting was removed rather than left
  in place claiming a protection that does not exist. A hung Batfish query
  therefore blocks its caller until the container is restarted. Enforcing it
  would need a supervising thread or a patched HTTP session; neither is
  justified for a single-user local tool yet.
