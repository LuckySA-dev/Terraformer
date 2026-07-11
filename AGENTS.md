# Repository guidance for coding agents

## Source of truth

Read `docs/network-automation-final-plan.md` in full before changing product
behavior. Preserve that final plan unchanged unless the user explicitly asks to
revise it. Record delivered behavior in `docs/IMPLEMENTATION_STATUS.md` and
vendor evidence in `docs/CAPABILITY_MATRIX.md`.

## Safety invariants

- Treat all network targets as real devices. Never infer permission to connect,
  scan, configure, reload, or erase a device.
- Routine automated tests must not contact a network device. Real-lab tests are
  separately marked, skipped by default, and require the opt-ins documented in
  `docs/lab-test-guide.md`.
- All device write capabilities are **Not Implemented** in phases 0–1. Do not
  add a write path under the label of a read-only change.
- Never log or commit credentials, private keys, raw unsanitized configuration,
  session cookies, provider keys, or generated `.secrets` files.
- Keep the normal Compose exposure on `127.0.0.1`; a broader bind is an explicit
  operator decision that requires the review in `docs/safety-model.md`.
- Preserve immutable snapshot semantics. Do not mutate an observed running
  configuration in place.
- Unknown or unverified vendor behavior fails closed to Safety Level D
  (read-only).

## Repository map

- `backend/`: FastAPI, RQ worker, migrations, drivers, and backend tests
- `frontend/`: React/Vite UI, reverse proxy image, and frontend tests
- `deploy/`: Compose definitions and non-destructive bootstrap scripts
- `docs/`: architecture, operations, safety, capability evidence, and status

Do not duplicate reverse-proxy routing in `deploy/`; the frontend image owns its
Nginx configuration. The API and worker must continue using the same backend
image with different commands.

## Local workflow

```text
python deploy/init-secrets.py
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.yml up --build --detach --wait
```

Use `.env.example` only for non-secret settings. The initializer is deliberately
non-rotating. Never replace `master.key` during an upgrade or test run.

Before handing off a change, run the relevant formatter, lint, type check, and
tests in both affected packages. Validate Compose with `docker compose config`
and keep documentation status conservative: implementation without fixture and
lab evidence is not `Supported`.

## Change discipline

- Prefer vertical slices with explicit error, timeout, and disconnected-state
  tests.
- Keep capability declarations separate from vendor driver implementation.
- Sanitize fixtures and use documentation-range addresses and fake hostnames.
- Do not introduce optional platforms, bulk writes, autonomous agents, or cloud
  deployment onto the phase 0–1 critical path.
- Preserve unrelated user changes in a dirty worktree.
