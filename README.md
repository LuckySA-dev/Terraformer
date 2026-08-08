# Terraformer Network Automation Playground

Terraformer is a local-first control workbench for inspecting real network
devices. The current phase establishes the repository, secure local deployment,
and a read-only Cisco IOS/IOS-XE vertical slice. It is designed for one local
administrator and a small management network.

> **Implementation boundary:** Phase 2 supports bounded, explicit IPv4 SSH-port
> discovery candidates, read-only Cisco CDP/LLDP observations, and an observed
> topology canvas with browser-local layouts and unverified manual links. Cisco
> routing, ARP, MAC, ping, and traceroute diagnostics use fixed or bounded
> commands. The Web terminal is warning-gated Direct Mode and can change a
> device; it has no rollback or recording. Structured device writes, automatic
> traversal/addition, and model-assisted features are not available. All device
> capabilities remain lab-unverified. Do not treat this repository as a
> production network controller.

> **Virtual labs:** devices can be marked as lab devices (GNS3, EVE-NG). Those
> may re-pin their SSH host key after a node restart, and — only when the server
> sets `TELNET_ENABLED` — may use a Telnet console. Telnet is cleartext with no
> host identity to verify; Terraformer never sends stored credentials over it.
> Keep it to an isolated lab.

The authoritative product scope is
[`docs/network-automation-final-plan.md`](docs/network-automation-final-plan.md).
Current implementation evidence and gaps are tracked in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## Start locally

Prerequisites:

- Docker Engine or Docker Desktop with Docker Compose v2
- Python 3.12 or newer for local secret initialization
- At least 4 CPU cores, 8 GB RAM, and 20 GB free disk for the core stack

The bootstrap wrapper creates missing local secrets without printing or
rotating them, builds the images, runs migrations, starts the stack, and waits
for service health.

PowerShell:

```powershell
.\deploy\start.ps1
```

Linux/macOS:

```bash
bash deploy/start.sh
```

Open <http://127.0.0.1:8080>. On first use, the application asks for the local
admin master password. That password is separate from the generated encryption
key in `.secrets/master.key`.

The wrappers use safe defaults when `.env` is absent. To customize non-secret
settings, copy `.env.example` to `.env` before starting. Never put device
passwords, API keys, or encryption keys in `.env`.

### Equivalent manual commands

```powershell
Copy-Item .env.example .env
py -3 deploy/init-secrets.py
docker compose --env-file .env -f deploy/compose.yml up --build --detach --wait
```

The secret initializer is idempotent: it retains valid existing files and
fails on invalid ones. It never rotates a key implicitly.

## Operate the stack

```powershell
# Service state and health
docker compose --env-file .env -f deploy/compose.yml ps

# API and worker logs (logs must remain sanitized)
docker compose --env-file .env -f deploy/compose.yml logs --follow api worker

# Stop without deleting data
docker compose --env-file .env -f deploy/compose.yml down
```

The web service is the only published service in the normal stack and binds to
`127.0.0.1:8080`. API traffic and WebSockets pass through its reverse proxy.
PostgreSQL and Redis have no host ports.

Check the two externally visible health routes:

```powershell
Invoke-WebRequest http://127.0.0.1:8080/healthz
Invoke-RestMethod http://127.0.0.1:8080/api/health
```

### Destructive reset

`docker compose --env-file .env -f deploy/compose.yml down --volumes` permanently
removes the database, queue state, and snapshots. Removing `.secrets/master.key`
makes any encrypted data that used it unrecoverable. Perform both actions only
for an intentional clean-room reset and never as routine troubleshooting.

## Develop

Generate secrets once, then start dependency containers with loopback-only
development ports:

```powershell
py -3 deploy/init-secrets.py
docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.dev.yml up --detach postgres redis
```

Backend:

```powershell
$env:APP_ENV = "development"
$env:DATABASE_HOST = "127.0.0.1"
$env:DATABASE_PORT = "5432"
$env:DATABASE_NAME = "terraformer"
$env:DATABASE_USER = "terraformer"
$env:DATABASE_PASSWORD_FILE = (Resolve-Path .secrets/postgres.password)
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:MASTER_KEY_FILE = (Resolve-Path .secrets/master.key)
$env:SNAPSHOT_DIR = (New-Item -ItemType Directory -Force .local/snapshots).FullName
Set-Location backend
uv sync --locked
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Frontend, in another terminal:

```powershell
Set-Location frontend
npm ci --cache .npm-cache
npm run dev
```

Use the scripts declared by each package for checks. The baseline commands are:

```powershell
Set-Location backend
uv run ruff check .
uv run pyright
uv run pytest

Set-Location ..\frontend
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

Real-device tests are excluded from routine test runs and require deliberate
opt-in. Read [`docs/lab-test-guide.md`](docs/lab-test-guide.md) before connecting
any device.

Every device connection requires an explicitly inspected and confirmed SSH host
key. The application stores one exact pin per registered device and has no
global relaxed host-key mode. The opt-in lab harness likewise requires an exact
`LAB_KNOWN_HOSTS_FILE`; keep connect and command timeouts separate.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — services, trust boundaries,
  persistence, and startup order
- [`docs/safety-model.md`](docs/safety-model.md) — mandatory security and device
  safety rules
- [`docs/CAPABILITY_MATRIX.md`](docs/CAPABILITY_MATRIX.md) — vendor capability
  evidence; every write capability is currently **Not Implemented**
- [`docs/user-guide.md`](docs/user-guide.md) — phase 0–1 user workflow
- [`docs/development.md`](docs/development.md) — contribution and validation flow

## Data and secret handling

- `.secrets/master.key` is a 32-byte URL-safe-base64 key mounted read-only into
  API and worker containers. It is separate from PostgreSQL and never committed.
- `.secrets/postgres.password` is mounted through file secrets; it is not placed
  in a process environment or database URL.
- PostgreSQL, Redis, and snapshot data live in named Docker volumes.
- Credentials and raw configuration must never appear in logs, diffs, fixtures,
  screenshots, support bundles, or documentation.
- Back up the master key separately from the database, with equivalent access
  controls. A database backup without its matching key cannot decrypt secrets.

There is no local model runtime or AI service in the phase 0–1 Compose stack.
