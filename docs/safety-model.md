# Safety model

Terraformer controls real network equipment. Safety is based on explicit
capabilities and evidence, not on a vendor name or optimistic fallback.

## Current enforcement boundary

Phases 0–1 are read-only. Every write capability in the capability matrix is
**Not Implemented**, and every driver is treated as Safety Level D for writes.
An absent write route is intentional defense in depth, not a missing UI shortcut.

Read operations still have side effects on fragile devices. The operator must
provide the exact target, authorize the connection, and use a lab or approved
management network. CIDR scanning and implicit neighbor traversal are not part
of the phase 1 flow.

## Safety levels

| Level | Meaning | Required UI wording |
|---|---|---|
| A | Native candidate, compare, confirmed commit, and rollback | Native transactional |
| B | Device-assisted rollback or replace for the tested feature | Device-assisted |
| C | Snapshot/diff/post-check; recovery requires connectivity | Best effort; never “auto-rollback” |
| D | Write path absent or not lab-verified | Read-only |

A vendor or OS version remains Level D until the exact capability has sanitized
fixtures and real-lab evidence. Evidence for one command family does not imply
support for another.

## Future mandatory apply pipeline

No stage may be skipped when writes are introduced in a later phase:

```text
Intent -> Structured Change Plan -> Vendor Render -> Validation -> Snapshot
       -> Diff and Risk -> Explicit User Confirmation -> Per-device Lock
       -> Apply -> Post-check -> Confirm/Rollback/Assisted Recovery -> Audit
```

Model output or wizard input can create intent only. Backend validation and a
human confirmation remain mandatory. Dangerous actions such as erase, reload,
format, and factory reset are outside the guided write path.

## Exposure rules

The normal stack publishes only the web service to `127.0.0.1`. Do not set
`HOST_BIND=0.0.0.0` merely for convenience. Before any LAN exposure:

1. terminate TLS with a certificate trusted by operator browsers;
2. restrict inbound traffic with the host firewall to the management segment;
3. set secure cookies and exact CSRF trusted origins;
4. verify forwarded-header handling and request-size limits;
5. protect host access to Docker, volumes, backups, logs, and secret files; and
6. retest authentication, logout, WebSocket origin checks, and recovery access.

Docker port binding does not make an application safe for untrusted networks.

## Secret rules

- Never pass a device password on a command line or store it on the device row.
- Never place secrets in `.env`, a Compose URL, logs, event detail, diff text,
  screenshots, exception messages, test artifacts, or fixtures.
- Encrypt credentials and sensitive snapshots with AES-GCM; unique nonces and
  authenticated metadata are required.
- Keep the encryption key separate from PostgreSQL. Mount it read-only and
  restrict its host permissions.
- Never rotate or regenerate `master.key` as part of startup, migration, test,
  restore, or upgrade.
- Back up database/snapshots and the matching key separately with equivalent
  access control, then test restore using sanitized data.

If a secret may have leaked, stop affected services, preserve sanitized audit
evidence, rotate the exposed credential at its source, and only then update the
encrypted profile. Do not paste it into an issue or support chat.

## Device and lab rules

- Routine tests use sanitized fixtures and documentation-range IP addresses.
- Real-device tests are skipped unless the operator opts in and names one exact
  target. See `lab-test-guide.md`.
- Never use production devices for development acceptance.
- Limit concurrency and command rate; the default maximum is 10 connections for
  the application, but a lab test should normally use one.
- Stop on unexpected prompts, privilege changes, parser uncertainty, timeouts,
  or a vendor/OS mismatch. Do not “try the closest driver.”
- The local-lab default `SSH_STRICT_HOST_KEY=false` accepts impersonation risk.
  Persistent or LAN-accessible deployments must mount a trusted `known_hosts`
  file and set it to `true`; never auto-accept a changed host key.
- Keep connection establishment (`SSH_CONNECT_TIMEOUT_SECONDS`, default 10) and
  command execution (`SSH_COMMAND_TIMEOUT_SECONDS`, default 30) as separate,
  bounded timeouts. A command timeout must not trigger an unbounded reconnect.
- Write tests in future phases require a current backup, console/OOB recovery,
  an approved maintenance window, and a separately documented change/recovery
  plan.

## Logging and audit

Structured logs and events must contain identifiers, timing, status, error
classifications, and hashes—not credentials or raw secret-bearing output. A
sanitizer is defense in depth; code must avoid sending sensitive values to the
logger in the first place. Any downloaded output must be sanitized and clearly
labelled as observed or inferred.
