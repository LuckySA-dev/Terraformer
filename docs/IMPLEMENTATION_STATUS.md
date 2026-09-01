# Implementation status

Last updated: 2026-09-01
Current delivery target: phases 0–4

This is the status ledger, not a roadmap. Product intent and future scope remain
in `network-automation-final-plan.md`.

The requirement-level Phase 1-2 closure audit is tracked in
`PHASE_1_2_READINESS.md`. It distinguishes missing implementation, automated
verification, virtual-lab evidence, and physical-lab evidence.

## Status meanings

- **Implemented** — code exists and required automated verification passes.
- **Lab unverified** — automated checks pass, but no device acceptance run
  (virtual or physical) has been recorded.
- **Not Implemented** — no supported product path.

**Evidence policy changed 2026-08-08 by owner decision:** a virtual-lab run
(GNS3/EVE-NG) satisfies phase exit, and physical-hardware evidence is no longer
required before starting the next phase. See `PHASE_1_2_READINESS.md` for what
that policy does and does not cover.

## Phase summary

| Phase | Status | Delivered boundary | Exit-criterion result |
|---|---|---|---|
| 0 — Repository and safety foundation | Implemented | Local Compose stack, file-secret bootstrap, PostgreSQL/Redis/RQ, migrations, health, authentication, encrypted credentials, sanitized logging, tests and operator docs | Passed automated and local-runtime acceptance |
| 1 — First real device | Implemented; **lab verified 2026-08-11** | Exact-target manual add, capability-gated Cisco IOS/IOS-XE structured read-only connection/facts/interfaces/running-config snapshots, generic authenticated connection test, jobs/events and operator UI | Automated acceptance passed, and the owner recorded a physical run on 2026-08-11 covering Cisco Catalyst 2960, 2960X, 3650 and ISR 2911: connection test plus structured facts/interface/neighbor reads passed for each category. Other vendors and models remain lab unverified |
| 2 — Topology and terminal | Implemented; **lab verified 2026-08-11** | Bounded multi-port SSH-aware discovery/approval; CDP/LLDP topology with saved layouts and unverified manual links; allowlisted show/ping/traceroute diagnostics; guarded Web PTY Direct Mode; Telnet console for lab devices | Automated acceptance passed. The 2026-08-11 physical run also covered CDP/LLDP collection and the Direct Mode terminal open/connect/disconnect lifecycle under Cisco Legacy mode for the same four device categories. Discovery, diagnostics and the Telnet console were not part of that run |
| 3 — Safe configuration MVP | Implemented; **apply/rollback still lab unverified** | Eleven Cisco IOS/IOS-XE change types gated by `STRUCTURED_WRITES_ENABLED` (off by default): interface description and admin state; VLAN name, access VLAN and trunk allowed-VLAN list; static route; router `network` statement, its removal, and RIP version; BGP neighbor; hostname. Change Plan preview with risk classification, per-device apply lock, apply, post-check, and assisted (inverse-command) rollback at Safety Level C, drivable from the Packet Tracer-style config window (several devices open at once) or its CLI tab | Automated acceptance passed (backend and frontend). No GNS3/EVE-NG or physical apply-and-rollback run has been recorded for **any** of the eleven types — see the verification record and known gaps below |
| 4 — AI assistant | Implemented; lab unverified | Optional (`AI_GATEWAY_ENABLED`, off by default) chat assistant over provider profiles in two wire formats — OpenAI-compatible (OpenAI, OpenRouter, Gemini compat, Ollama, LM Studio) and native Anthropic. Nine tools: eight read-only, plus `propose_change_plan`, which drafts into the same Change Plan pipeline rather than touching a device. Confirm/Auto modes with a per-session automatic-apply cap; suggested console commands are staged for human review, never relayed live; provider secrets are scrubbed defensively; long conversations are compacted rather than truncated | Automated acceptance passed. No model provider was contacted and no device was driven by the assistant in any recorded run |
| 5–8 | Not Implemented | None | Future phases |

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
| Every structured device write capability beyond Phase 3's scope | **Not Implemented** | Phase 3 (below) adds exactly two Cisco IOS/IOS-XE capabilities at Safety Level C; every other vendor and capability stays Not Implemented; manual Direct Mode is outside structured Safety Levels A–D and can write/change hardware |

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

## Phase 3 checklist

| Item | Status | Evidence |
|---|---|---|
| Change Plan pipeline | Implemented; lab unverified | Preview, validate, risk classification, pre-change snapshot, per-device apply lock, apply, post-check and assisted inverse-command rollback, all at Safety Level C behind `STRUCTURED_WRITES_ENABLED` |
| Eleven Cisco IOS/IOS-XE change types | Implemented; lab unverified | Interface description and admin state; VLAN name, access VLAN, trunk allowed-VLAN list; static route; router `network`, `network` removal, RIP version; BGP neighbor; hostname. Change types are stored as `VARCHAR` rather than a database enum, so adding one needs no migration |
| Device reads the change types depend on | Implemented; lab unverified | `show vlan brief`, `show interfaces switchport`, `ip route` and `router` sections of the running config, parsed from sanitized fixtures |
| Free-text input cannot smuggle commands | Implemented | `validate_change` rejects non-printable and empty values before a plan exists; a `"looks-fine
shutdown"` description returns 422 and creates no plan (found by review 2026-08-09, regression test retained) |
| Applied commands are recorded verbatim | Implemented | The log sanitizer no longer rewrites the command text stored with a plan, so the record matches what the device received |
| Plans cannot stick in `APPLYING` | Implemented | Apply catches every exception, not only `AppError`, and settles the plan into a terminal state |
| Config window | Implemented; lab unverified | Packet Tracer-style window with up to six devices open at once, per-window state preserved, a Config tab covering every change type and a CLI tab that holds its SSH session across tab switches; apply reports what the device actually did, including `ROLLBACK_FAILED` |
| Real-device apply and rollback | **Not verified** | Opt-in test at `backend/tests/lab/test_structured_writes_lab.py` skips cleanly when unset; it has never been run against a real or virtual device |

## Phase 4 checklist

| Item | Status | Evidence |
|---|---|---|
| Provider profiles | Implemented; lab unverified | CRUD plus capability probe behind `AI_GATEWAY_ENABLED` (off by default); API keys encrypted with the same server-side scheme as device credentials and never returned |
| Two wire formats | Implemented; lab unverified | One adapter for everything speaking OpenAI Chat Completions (OpenAI, OpenRouter, Gemini compat, Ollama, LM Studio) and a native Anthropic adapter; the provider type selects the adapter |
| Session and message persistence | Implemented | Migrations through `20260829_0018`; replay order rests on an explicit `sequence` column rather than a timestamp, which collided often enough to reorder transcripts |
| Bounded multi-round tool loop | Implemented | Twelve rounds and forty tool calls per turn, with a bounded result size per tool |
| Tool surface | Implemented | Eight read-only tools plus `propose_change_plan`, which drafts into the Change Plan pipeline and cannot reach a device on its own |
| Confirm/Auto modes | Implemented | Automatic apply is capped per session; AI-drafted plans are marked by source so they stay distinguishable from operator-drafted ones |
| Console commands are staged, not relayed | Implemented | Suggested commands are presented for human review; the assistant has no path to the PTY |
| Context window accounting and compaction | Implemented | A long conversation is summarised at 80% of the model's context and the newest messages are kept verbatim; the operator's own question and the leading system messages are pinned and can no longer be dropped by the trimmer |
| Any real provider or device run | **Not verified** | No model provider was contacted and no device was driven by the assistant in any recorded run |

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

| 2026-08-08 | Post-hardware-test defect closure (migration, add-device, legacy SSH, lab/telnet, UI) | Backend Ruff, Pyright, complete pytest; frontend typecheck, lint, complete Vitest, production build; `alembic upgrade head` + `alembic check`; `docker compose config --quiet` | **Automated verification passed; hardware validation pending.** Backend 309 passed / 1 opt-in lab skipped; frontend 13 files / 146 tests plus typecheck, lint and production build passed; no Alembic model drift. **Correction to the prior record:** re-running the suite at commit `9fc21fc` reproduced **8 pre-existing failures**, so the "285 passed" entry below did not hold at that commit. |
| 2026-08-08 | Migration chain on real PostgreSQL 17 | `postgres:17.10-alpine3.23` container; `pytest tests/integration/test_migrations.py` with `TEST_POSTGRES_URL`; complete backend suite with the same variable | **Verified on the dialect that actually failed.** 8 migration tests and 312 backend tests passed. The pre-fix migration was re-run against the same server and reproduced the reported failure exactly — `psycopg.errors.InFailedSqlTransaction: current transaction is aborted`, caused by dropping the non-existent `ck_devices_vendor` — confirming both the diagnosis and the fix. Downgrade past `20260806_0005` with a stored `fortinet_fortios` device correctly raises instead of truncating the column, and the device is left intact. |
| 2026-08-08 | Compose runtime | `docker compose --env-file .env -f deploy/compose.yml up --build --detach --wait`; container `alembic current`/`check`; `ssh -V`; health routes | **Runtime verified.** Images built; `migrate` exited 0; PostgreSQL, Redis, API, worker and web all reported healthy; `GET /healthz` returned 200 and `GET /api/health` reported database, Redis and worker `ok`. The previously pending backend-image `ssh -V` smoke test now passes: **OpenSSH_9.2p1 Debian-2+deb12u10**, which both supports `RequiredRSASize` (OpenSSH 9.1+) and is the version that enforces the 1024-bit RSA host-key floor the legacy modes exist to lower. |
| 2026-08-08 | Existing-database repair (`20260808_0007`) | The running Compose database, which was already stamped at head with the un-widened column; `alembic upgrade head`; `alembic check`; direct insert | **A defect only a real deployment revealed.** That database sat at head with `devices.vendor` still `VARCHAR(11)`, because it had been stamped past the failing `20260806_0005` rather than re-running it — so registering a Fortinet device would still have failed. `20260808_0007` reconciles both enum columns idempotently: `vendor` widened 11 → 16, exactly one canonical CHECK per column, `alembic check` clean, and an insert of `fortinet_fortios` / `very_old_ssh` (previously rejected) now succeeds. |
| 2026-08-09 | Phase 3 safe configuration slice (backend/frontend) | `.venv/Scripts/python.exe -m ruff check --no-cache .`; `.venv/Scripts/pyright.exe`; `.venv/Scripts/python.exe -m pytest -q`; frontend `npm run typecheck`; `npm run lint`; `npm test -- --run`; `npm run build`; `docker compose --env-file .env.example -f deploy/compose.yml config --quiet` | **Automated verification passed.** Ruff and Pyright clean (0 errors/0 warnings). Backend 377 passed / 6 skipped (all opt-in: Batfish, lab Cisco read, lab structured-write apply/rollback, 3× `TEST_POSTGRES_URL`-gated migration tests). Frontend: TypeScript, ESLint, 153 tests (14 files), and the Vite production build all passed. Compose config valid. No device connection or external network operation was performed. |
| 2026-08-09 | Phase 3 migration chain on real PostgreSQL 17 | `postgres:17.10-alpine3.23` throwaway container; `TEST_POSTGRES_URL=... pytest tests/integration/test_migrations.py -v`; same variable for the complete backend suite; `alembic upgrade head`; `alembic check` | **Deferred obligation from Task 1, now discharged.** All 9 migration tests passed, including the new `test_change_plan_tables_exist_after_upgrade`; complete backend suite 380 passed / 3 skipped (only the two opt-in real-device/Batfish tests remained gated). `alembic upgrade head` reached `20260809_0009` and `alembic check` reported no model drift. Container and its anonymous volume were removed after the run. |
| 2026-08-09 | Phase 3 post-implementation review (defects found and fixed) | Line-by-line review of the change pipeline against the safety model; new regression tests at `tests/unit/test_drivers.py` and `tests/integration/test_changes_vertical_slice.py`; full backend and frontend suites | **Three defects found by review, not by the original tests.** (1) **Command injection in the one free-form input:** an interface description containing a newline rode through `render_change` into a single line, was persisted newline-joined, and split back into an extra configuration command at apply — defeating the premise that only vetted change types reach a device. `validate_change` now rejects any non-printable value (and empty/whitespace-only), refused before a plan is ever created; proved end-to-end with a `"looks-fine\nshutdown"` payload that now returns 422 and leaves no plan. Interface targets were never exposed: they are matched against names parsed from the device. (2) Driver validation failures returned HTTP 500 via a bare `AppError`; they are operator input errors and now return 422 `change_validation_failed`. (3) The Configure tab rendered preview errors but silently swallowed apply errors (including the 409 device lock), and never surfaced `ROLLBACK_FAILED` — the one outcome the safety model says needs manual device verification. Backend 380 passed / 6 opt-in skipped; frontend 155 passed. |
| 2026-08-09 | Phase 3 real-lab apply/rollback: **not run** | Opt-in test written at `backend/tests/lab/test_structured_writes_lab.py` (`RUN_LAB_TESTS=1` plus `LAB_DEVICE_*` and `LAB_TARGET_INTERFACE`); confirmed to skip cleanly with a clear reason when unset | **Not executed — no GNS3/EVE-NG or physical Cisco IOS/IOS-XE device was available in this environment.** Per this plan's Global Constraints (Approved Decision 3), this is recorded honestly rather than omitted: the apply-and-rollback pipeline has sanitized fixture/unit/integration coverage (including a fake-transport vertical slice exercising preview → apply → post-check → device-scoped lock) but has never been exercised against a real or virtual device. Cisco IOS/IOS-XE interface changes stay **Level C, lab unverified** — see `docs/CAPABILITY_MATRIX.md`. Running this test against a real lab device remains the outstanding acceptance step for Phase 3. |
| 2026-08-11 | Cisco Legacy SSH: physical lab run by the owner | Connection test, structured facts/interface/neighbor read, and Direct Mode terminal open/connect/disconnect through the UI, per device category | **Physical hardware, not a simulation.** Cisco Catalyst 2960, 2960X, 3650 and ISR 2911 all passed under Cisco Legacy compatibility mode (recorded at commit `48b776d`). This is the device acceptance evidence phases 1 and 2 had been waiting on. It does not extend to other vendors or models, to discovery, to the allowlisted diagnostics, to the Telnet console, or to any structured write. Full record in `docs/lab-test-guide.md`; capability-level detail in `docs/CAPABILITY_MATRIX.md` and `docs/PHASE_1_2_READINESS.md` |
| 2026-09-01 | Full regression after 59 commits of Phase 3 expansion, Phase 4, and the interface redesign | Backend `ruff check --no-cache .`, `pyright`, `pytest -q`; frontend `tsc --noEmit`, `eslint src --max-warnings 0`, `vitest run --no-file-parallelism`, `npm run build`; `docker compose --env-file .env -f deploy/compose.yml up --build --detach web` | **Automated verification passed.** Ruff clean; Pyright 0 errors, 0 warnings, 0 informations; backend **692 passed / 7 skipped**, every skip opt-in (3 gated on `TEST_POSTGRES_URL`, 2 on `RUN_LAB_TESTS`, 2 on `RUN_ANALYSIS_TESTS`). Frontend TypeScript and ESLint clean; **312 tests / 24 files passed** run serially, and the production build passed. Note the suite is only reliably green serially: under file parallelism 2-3 tests intermittently exceed the 5 s timeout and fail, which is a harness contention issue, not a product defect — the same files pass 72/72 in isolation. Migration head `20260829_0018`. No provider was contacted, no device connected, and no lab opt-in supplied |
| 2026-09-01 | Interface re-identity: defects found by measuring the running app | Computed-style and layout measurement in the browser against the built image; hue sweep over every source file; a CSS specificity scan for modifier rules defeated by later base rules | **Three real defects, none visible in code review.** (1) A bare `.workspace-layout` inside the `<=1260px` media query outranked `.workspace-layout--inspector-collapsed` by source order, so every page below that width reserved a 340 px inspector column that nothing occupied; the content column measured 634 px beside it and the non-wrapping 835 px toolbar pushed the workspace into a horizontal scroll. (2) The topology graph draws to a canvas and cannot read a `var()`, so its palette was a hand-copied duplicate of the tokens — and had gone stale, still drawing the pre-redesign accent and reds. It now resolves the same custom properties the DOM uses. (3) 58 greys across the app still carried the old accent's green cast, and the link-up indicators were hardcoded to a colour that never followed the theme. The specificity scan found two further modifier/base clashes, both verified deliberate and harmless |

## Known defects found and fixed on 2026-08-08

Reported after a real-device test session, all traceable to commit `9fc21fc`:

- **Migration failed on Docker/PostgreSQL.** `20260806_0005` dropped
  `ck_devices_vendor`, a constraint that never existed — `sa.Enum` defaults to
  `create_constraint=False`. On PostgreSQL a failed DDL statement aborts the
  whole transaction, so `alembic upgrade head` failed and the API and worker
  never started. SQLite tolerated it, so no test caught it.
- **`devices.vendor` was too narrow.** The column was `VARCHAR(11)`, sized to
  the original two-value enum, while `fortinet_fortios` is 16 characters.
  PostgreSQL rejects the insert; SQLite ignores VARCHAR length.
- **Adding a device returned 422.** The frontend sent
  `very_old_risk_acknowledged`, which the request schemas did not declare and
  `extra="forbid"` rejected. Frontend tests mock `fetch`, so no test exercised
  the real schema.
- **Duplicate/stale CHECK constraints** left `ssh_compatibility` restricted to
  its pre-`very_old_ssh` values.
- **Model/migration drift** on `device_ssh_host_keys` made `alembic check` fail,
  contrary to the earlier record.
- **Databases stamped past the broken migration stayed broken.** Running the
  real stack showed a database recorded at head while `devices.vendor` was still
  `VARCHAR(11)`, because the usual way out of the original failure is
  `alembic stamp`. `20260808_0007` repairs both enum columns idempotently, so no
  operator has to work out how their database got there.
- **Legacy Cisco SSH could not connect.** OpenSSH ≥ 9.1 enforces a 1024-bit
  minimum RSA host key, which no algorithm option can override, and Catalyst
  2960/2960-X and ISR 1941 commonly present 512/768-bit keys. The legacy modes
  now set `RequiredRSASize=768`, and the failure maps to a negotiation error
  instead of being reported as an authentication failure.

New regression guards: migrations are executed and `alembic check` is asserted;
a contract test posts the frontend's exact payloads to every device endpoint;
and an opt-in `TEST_POSTGRES_URL` test runs the chain against real PostgreSQL.

## Security decisions verified

- Device credentials are encrypted server-side with AES-GCM and are never
  returned by credential APIs.
- The local administrator password is stored only as an Argon2id verifier.
- Snapshots are compressed before encryption, use authenticated context, reject
  tampering/path traversal and cannot be overwritten in storage or PostgreSQL.
- State-changing browser requests enforce trusted-origin checks; session cookies
  are HttpOnly and SameSite strict.
- Structured driver operations are capability-gated. **Updated 2026-09-01:**
  the claim that no configuration apply or model-execution path exists is no
  longer true and has been corrected here. Both now exist and both are off by
  default — configuration apply behind `STRUCTURED_WRITES_ENABLED`, the model
  path behind `AI_GATEWAY_ENABLED`. Apply is confined to eleven vetted change
  types at Safety Level C; free-text values are refused if they contain
  anything non-printable, so a change cannot carry a second command. The
  assistant reaches devices only through read-only tools and by drafting into
  the same Change Plan pipeline a human drafts into; it has no path to the PTY,
  and suggested console commands are staged for human review rather than
  relayed. Manual terminal access is isolated as warning-gated Direct Mode and
  does not log commands or output. Discovery candidates and neighbor records do
  not create topology nodes or links automatically.

## Known gaps

- ~~No device acceptance run is recorded yet.~~ **Closed 2026-08-11:** the
  owner ran Cisco Catalyst 2960, 2960X, 3650 and ISR 2911 on physical hardware
  — connection test, structured facts/interface/neighbor reads, and the Direct
  Mode terminal lifecycle, all passing under Cisco Legacy mode. Cisco reads are
  **lab verified for those four categories only**. Every other vendor, model
  and compatibility mode is still lab unverified, and nothing about structured
  writes was exercised by that run.
- Mandatory host-key pinning and its explicit UI enrollment flow have automated
  coverage only. No unknown or changed key is trusted automatically, and no
  authorized metadata-only virtual or physical acceptance record exists yet.
- ~~The backend-image `ssh -V` smoke test is pending.~~ **Closed 2026-08-08:**
  the rebuilt image reports OpenSSH_9.2p1, which provides the `RequiredRSASize`
  option the legacy SSH modes depend on.
- Manual USB Console automated verification passed, but hardware validation is
  pending. It remains lab-unverified, and no device/vendor support is inferred
  from browser, fake-stream, serving-policy, or local Compose evidence. Manual
  Direct Mode is outside structured Safety Levels A–D and can write/change
  hardware.
- Structured configuration writes are optional (`STRUCTURED_WRITES_ENABLED`,
  off by default) and cover eleven change types on Cisco IOS/IOS-XE only:
  interface description and admin state; VLAN name, access VLAN and trunk
  allowed-VLAN list; static route; router `network`, its removal and RIP
  version; BGP neighbor; hostname. **None of the eleven has been applied to a
  real or virtual device** — the expansion from two types to eleven added no
  lab evidence, so the whole set is lab unverified, not just the new members.
  Other vendors and any Safety Level above C remain Not Implemented. A trunk
  allowed-VLAN change replaces the list rather than adding to it, which is why
  risk classification treats it the way it does. Rollback is
  surgical (inverse commands from the rendered change), never a full
  running-config replay. `ROLLBACK_FAILED` is a real, expected outcome of
  Level C and requires manual device verification when it occurs — it is
  not a bug class this phase attempts to eliminate. No re-validation is
  performed immediately before push; a plan applies exactly what it showed
  the operator at preview time, and post-check is the only safety net
  against device state that drifted since then.
- Backup/restore acceptance is not implemented in phases 0–4.
- Broader LAN exposure has not been hardened or tested; normal deployment stays
  loopback-only.
- Phase 2's topology and terminal claims were met by the 2026-08-11 physical
  run for the four Cisco categories it covered. Discovery, the allowlisted
  diagnostics and the Telnet console were **not** part of that run and keep
  automated coverage only. Phase 3's apply-and-rollback acceptance run remains
  outstanding (see the verification record above) — its opt-in test exists and
  has automated fixture coverage, but has never been run against a real or
  virtual device.
- The Telnet console for lab devices has automated coverage only. It is
  cleartext with no host identity, is off unless `TELNET_ENABLED` is set, and is
  refused for any device not marked as a lab device. Credentials are never sent
  automatically over it.
- `RequiredRSASize=768` in the legacy SSH modes is the fix for undersized RSA
  host keys on Catalyst 2960/2960-X and ISR 1941. It is covered by unit tests
  only; no such device has been contacted. It also requires OpenSSH 9.1+ in the
  backend image (Debian bookworm ships 9.2).
- Direct Mode is an explicit operator escape hatch and can change a device. It
  has no parser, approval plan, rollback guarantee, or recording by design.
- Cisco Legacy SSH terminal and topology claims are lab verified for Catalyst
  2960, 2960X, 3650 and ISR 2911 as of 2026-08-11, and remain lab unverified
  everywhere else. The compatibility-policy version, kill switches and resource
  limits still have automated coverage only — the lab run exercised the happy
  path, not the limits.

- The AI assistant (`AI_GATEWAY_ENABLED`, off by default) has automated
  coverage only. No model provider has been contacted in any recorded run, so
  nothing is known about how a real model behaves against the tool loop: the
  bounded rounds, the per-session automatic-apply cap, and compaction of a long
  conversation are all enforced in code and proven by tests, not by a provider.
  An assistant-drafted Change Plan is applied through exactly the same pipeline
  and the same Level C guarantees as an operator-drafted one, so it inherits
  that pipeline's outstanding lab gap rather than having a separate one.
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
