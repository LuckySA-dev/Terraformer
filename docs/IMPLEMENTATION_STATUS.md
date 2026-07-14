# Implementation status

Last updated: 2026-07-12
Current delivery target: phases 0–2

This is the status ledger, not a roadmap. Product intent and future scope remain
in `network-automation-final-plan.md`.

## Status meanings

- **Implemented** — code exists and required automated verification passes.
- **Lab unverified** — automated checks pass, but real-device acceptance has not
  been recorded.
- **Not Implemented** — no supported product path.

## Phase summary

| Phase | Status | Delivered boundary | Exit-criterion result |
|---|---|---|---|
| 0 — Repository and safety foundation | Implemented | Local Compose stack, file-secret bootstrap, PostgreSQL/Redis/RQ, migrations, health, authentication, encrypted credentials, sanitized logging, tests and operator docs | Passed automated and local-runtime acceptance |
| 1 — First real device | Implemented; exit blocked — lab unverified | Exact-target manual add, capability-gated Cisco IOS/IOS-XE read-only connection/facts/interfaces/running-config snapshots, generic authenticated connection test, jobs/events and operator UI | Automated acceptance passed; phase exit requires an authorized real Cisco read-only run, which is not recorded |
| 2 — Topology and terminal | Implemented; exit blocked — lab unverified | Bounded discovery/approval; CDP/LLDP topology with saved layouts and unverified manual links; allowlisted show/ping/traceroute diagnostics; guarded Web PTY Direct Mode | Automated and local-runtime acceptance passed; phase exit still requires an authorized lab topology plus terminal/diagnostic evidence |
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
| Sanitized structured logging and typed errors | Implemented | Unit/integration tests and runtime log review |
| Default loopback exposure | Implemented | Only web is published, on `127.0.0.1:8080` |
| No model runtime in base deployment | Implemented | No model/AI service exists in Compose |

## Phase 1 checklist

| Item | Status | Evidence |
|---|---|---|
| Cisco IOS/IOS-XE connection test | Implemented; lab unverified | Capability/transport unit tests and opt-in lab harness |
| Exact-target manual add | Implemented; lab unverified | API/service/UI vertical-slice tests; no CIDR discovery path |
| Facts collection | Implemented; lab unverified | Sanitized golden fixtures and parser/driver tests |
| Interface inventory/state | Implemented; lab unverified | Sanitized golden fixtures and API/UI tests |
| Immutable running-config snapshot | Implemented; lab unverified | Compress-then-encrypt, tamper, traversal and no-overwrite tests; PostgreSQL immutable trigger present |
| Read-only device inspector and event timeline | Implemented | React component and API tests; visual QA against running Compose stack |
| Generic/unknown platform | Implemented; lab unverified | Authenticated SSH connection test only; other capabilities fail closed |
| Every device write capability | **Not Implemented** | Required current safety boundary |

## Phase 2 checklist

| Item | Status | Evidence |
|---|---|---|
| Cisco CDP/LLDP neighbor collection | Implemented; lab unverified | Sanitized parser fixtures, capability/error tests, refresh job integration |
| Neighbor persistence and API | Implemented; lab unverified | Migration `20260712_0002`, replacement semantics, typed authenticated endpoint |
| Observed-neighbor inspector | Implemented | React component test; records labeled `OBSERVED` |
| Bounded IPv4 SSH discovery and approve flow | Implemented; lab unverified | Maximum 64 addresses, bounded concurrency/timeout/rate, one active scan at a time in API/UI, atomic approval audit, fake-probe tests, no credentials or automatic inventory creation |
| Read-only topology canvas and links | Implemented; lab unverified | Cytoscape projection of registered devices and saved CDP/LLDP records; browser-local node positions; manual/30/60-second view refresh; interface-pair labels; browser-local manual links always labeled `UNVERIFIED` |
| Allowlisted Cisco diagnostics | Implemented; lab unverified | Typed routing/ARP/MAC plus bounded exact-IPv4 ping/traceroute actions; fixed driver mappings; RQ execution; sanitized 64 KiB cap and local download; injection/timeout/unsupported tests |
| Web SSH terminal | Implemented; lab unverified | AsyncSSH PTY over authenticated same-origin WebSocket; explicit Direct Mode confirmation before credential decrypt/connect; three-session server/UI cap; 15-minute input idle timeout; 2 MiB output cap; no command/output recording |

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
- No write capability is implemented.
- Backup/restore acceptance is not implemented in phases 0–2.
- Broader LAN exposure has not been hardened or tested; normal deployment stays
  loopback-only.
- Phase 2 automated implementation is complete, but its exit cannot be promoted
  without an authorized real-lab topology plus terminal/diagnostic run. Phase 3
  remains intentionally unstarted until that evidence exists.
- Direct Mode is an explicit operator escape hatch and can change a device. It
  has no parser, approval plan, rollback guarantee, or recording by design.
- The final typed WebSocket error guard for a missing terminal device passed
  lint, types, and the full backend suite after runtime deployment. A final API
  image rebuild was blocked by the Codex execution quota, so the currently
  healthy local API image is one source-only guard behind the worktree.
