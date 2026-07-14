# Architecture

## Phase 0–2 boundary

The system is a single-user local application for 1–50 registered devices. The
current vertical slice supports an operator-started IPv4 SSH-port probe capped at
64 addresses, explicit candidate approval, observed Cisco CDP/LLDP neighbors,
an observed Cytoscape projection, background Cisco routing/ARP/MAC/ping/
traceroute actions selected from a backend allowlist, and a guarded AsyncSSH PTY
terminal. Diagnostic output is sanitized and capped at 64 KiB before persistence.
It does not traverse neighbors, add devices automatically, or expose a
structured device-configuration path. Layout and unverified manual links are
browser-local until backup/restore scope is implemented.

```text
Browser
  -> web (Nginx static UI + reverse proxy, 127.0.0.1:8080)
      -> api (FastAPI, internal port 8000)
          -> PostgreSQL 17 (inventory, jobs, events, metadata)
          -> Redis 7 (RQ queue and worker registration)
          -> encrypted snapshot volume
      -> `/ws/terminal/{device_id}` (authenticated, same-origin Direct Mode PTY)

worker (same backend image as api)
  -> PostgreSQL / Redis
  -> explicitly approved management-network device
```

There is no load balancer, PostgreSQL replica, Redis Sentinel, time-series
database, AI gateway container, or local model runtime in this phase.

## Services

| Service | Responsibility | Host exposure | Persistence |
|---|---|---|---|
| `web` | Static SPA and `/api`/`/ws` reverse proxy | `127.0.0.1:8080` by default | None |
| `api` | REST API, local session, validation | None in normal stack | Shared snapshots |
| `worker` | Blocking device and background jobs | None | Shared snapshots |
| `migrate` | One-shot `alembic upgrade head` | None | PostgreSQL schema |
| `postgres` | Authoritative application records | None | `postgres_data` |
| `redis` | Queue, status, and transient coordination | None | `redis_data` AOF |

`deploy/compose.dev.yml` explicitly publishes API, PostgreSQL, and Redis on
loopback for host-native development. It must not be used to expose those
services to a management LAN.

## Networks and trust boundaries

`web` and `api` share the `edge` network. Only backend services join the
`application` network, so the reverse proxy cannot connect directly to the
database or queue. The application network retains outbound routing because the
worker must reach explicitly approved devices on the management network.

The host bind address is a security boundary, not an authentication mechanism.
Changing `HOST_BIND` from `127.0.0.1` requires TLS, host firewall rules, a trusted
management segment, and a review of proxy headers, cookies, CSRF origins, and
access logs.

The local-lab stack explicitly disables strict SSH host-key verification for
first contact. This is a convenience/risk tradeoff, not a secure deployment
default. Persistent installations must provision trusted host keys and enable
strict verification before device connections.

## Startup and readiness

Compose starts PostgreSQL, waits for `pg_isready`, and runs the one-shot
migration. API and worker start only after migration succeeds and Redis is
healthy. The API readiness endpoint returns an error while required dependencies
are unavailable. The web service starts after API readiness and is the sole
entry point.

The worker health command checks live RQ registration rather than merely testing
that Redis accepts connections. It uses the queue-specific RQ registry so stale
or incomplete general worker metadata cannot produce a false negative.

## Secret flow

`deploy/init-secrets.py` creates two ignored host files:

- `master.key`: 32 random bytes encoded as URL-safe base64
- `postgres.password`: an independent random database password

Compose mounts both as read-only file secrets. API and worker read the master
key from `/run/secrets/terraformer_master_key` and the database password from
`/run/secrets/postgres_password`. PostgreSQL reads that same password via its
`POSTGRES_PASSWORD_FILE` contract. Secret values do not appear in Compose
environment output or a database URL.

The application master password is not the encryption key. It is established by
the first-run setup flow, stored only as a password hash, and used to establish
the local session.

## Data ownership

| State | Owner | Rule |
|---|---|---|
| Devices, interfaces, and observed neighbors | PostgreSQL | Device secrets are referenced, not embedded |
| Credential ciphertext | PostgreSQL | AES-GCM data; key remains outside the database |
| Running-config snapshots | Snapshot volume + metadata | Immutable observed state |
| Jobs and events | PostgreSQL | Sanitized, append-oriented history |
| Queue payload/status | Redis | No plaintext credential payloads |
| Master key | Host secret file | Back up separately; never rotate implicitly |

Redis is not an authoritative store. Loss of Redis may discard queued work but
must not erase the inventory or audit history. Loss of the matching master key
makes encrypted credentials and artifacts unrecoverable.

## Scale assumptions

The initial target is 1–50 devices and a default maximum of 10 concurrent device
connections. One device operation is one job. Bulk operations and scale beyond
50 devices require measured queue, connection, and device-load testing before
the architecture is widened.
