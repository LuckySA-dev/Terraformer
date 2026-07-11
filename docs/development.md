# Development and verification

## Baseline workflow

1. Read `network-automation-final-plan.md` and the relevant status/matrix rows.
2. Generate ignored file secrets with `python deploy/init-secrets.py`.
3. Start PostgreSQL 17 and Redis 7 using the development Compose override.
4. Make one bounded vertical-slice change.
5. Run formatter, lint, type checks, unit/integration tests, and image builds for
   every affected package.
6. Validate Compose interpolation and service health.
7. Update implementation status and capability evidence conservatively.

Routine tests must be deterministic and must not open connections to lab or
production networks.

## Dependency stack

```powershell
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.dev.yml up --detach postgres redis
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.dev.yml ps
```

The override publishes ports on `127.0.0.1` only. Database authentication still
uses the generated password file.

## Backend checks

```powershell
Set-Location backend
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

Tests should cover success, authentication failure, timeout, disconnect,
malformed output, unsupported capability, and sanitizer behavior. Network
drivers use sanitized, versioned fixtures—not live sockets.

## Frontend checks

```powershell
Set-Location frontend
npm ci --cache .npm-cache
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

The frontend must make same-origin `/api` and `/ws` requests through Nginx in
the container image. Absolute development URLs must remain runtime/development
configuration and must not be baked into the production bundle.

## Compose validation

Run secret initialization first because Compose validates secret file paths.

```powershell
py -3 deploy/init-secrets.py
docker compose --env-file .env -f deploy/compose.yml config --quiet
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.dev.yml config --quiet
docker compose --env-file .env -f deploy/compose.yml build
docker compose --env-file .env -f deploy/compose.yml up --detach --wait
docker compose --env-file .env -f deploy/compose.yml ps
```

Expected normal exposure: only `127.0.0.1:${WEB_PORT:-8080}` is published. The
development override may additionally publish API, PostgreSQL, and Redis, all on
the configured loopback address.

## Migration discipline

- Every schema change has an Alembic upgrade and a reviewed downgrade or an
  explicit explanation why reversal is unsafe.
- Test migration from an empty database and from the previous schema revision.
- The one-shot `migrate` service must succeed before API and worker start.
- Migrations must not rotate keys, decrypt/re-encrypt all credentials implicitly,
  or contact devices.

## Fixtures and documentation

Use RFC 5737 IPv4 documentation ranges, RFC 3849 IPv6 documentation addresses,
fake serials, and non-identifying hostnames. Sanitize banners and configuration
text before adding a fixture. A capability remains lab-unverified until a dated,
sanitized real-lab evidence record is added to `CAPABILITY_MATRIX.md`.

## Clean-up

`docker compose -f deploy/compose.yml down` is non-destructive. Do not automate
`down --volumes`, secret deletion, database restore, or key rotation in ordinary
development commands.
