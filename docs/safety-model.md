# Safety model

Terraformer controls real network equipment. Safety is based on explicit
capabilities and evidence, not on a vendor name or optimistic fallback.

## Current enforcement boundary

Structured automation in phases 0–2 is read-only. Every structured write
capability in the capability matrix is **Not Implemented**, and every driver is
treated as Safety Level D for writes. An absent structured write route is
intentional defense in depth, not a missing UI shortcut.

Read operations still have side effects on fragile devices. The operator must
provide the exact target or bounded IPv4 range, authorize the operation, and use
a lab or approved management network. Discovery is capped at 64 addresses, uses
bounded concurrency/timeouts/rate, stores only open-port candidates, and never
adds a device automatically. Implicit neighbor traversal is not implemented.
Diagnostics accept only typed routing, ARP, MAC, ping, and traceroute actions for
a registered device. The Cisco driver maps each action to one fixed or bounded
command; ping/traceroute accepts one validated exact IPv4 target. Output is
sanitized, capped at 64 KiB, and recorded without raw output in event details.
Generic and unknown drivers fail closed.

The terminal is a separate Direct Mode path, not a structured driver capability.
It requires an authenticated same-origin WebSocket and an explicit warning
acknowledgement before credentials are decrypted or SSH begins. Three-session,
input-idle, per-message input, and total-output limits bound resources. Commands
and output are never logged or stored. Direct Mode can change a device and has
no command parser or rollback guarantee; the warning is an operator boundary,
not a claim that the terminal is read-only.

Legacy and Very Old SSH compatibility is device-scoped under
`compatibility_policy_version = 2`. `modern` remains the default and has no
legacy override or automatic fallback. `cisco_legacy` may append only
`diffie-hellman-group14-sha1`, `diffie-hellman-group-exchange-sha1`, `ssh-rsa`,
`aes256-cbc`, `aes192-cbc`, `aes128-cbc`, `hmac-sha1`, and `hmac-sha1-96` after
modern defaults; `cisco_legacy_group1` additionally appends
`diffie-hellman-group1-sha1` as a last resort. For older lab hardware (such as Cisco 1941 routers, Catalyst 2950 switches, or legacy Fortinet FortiOS devices), `very_old_ssh` additionally appends obsolete cryptographic algorithms including `ssh-dss`, `diffie-hellman-group1-sha1`, `hmac-md5`, `hmac-md5-96`, and `3des-cbc`. SSHv1 and RC4 remain completely forbidden and unsupported.
`SSH_LEGACY_ENABLED=false`, `SSH_GROUP1_ENABLED=false`, `SSH_VERY_OLD_ENABLED=false`, and `SSH_TERMINAL_ENABLED=true` are server-side
kill switches evaluated before every connection. Selecting `very_old_ssh` requires all three compatibility kill switches (`SSH_LEGACY_ENABLED`, `SSH_GROUP1_ENABLED`, `SSH_VERY_OLD_ENABLED`) to be enabled simultaneously. Compatibility does not change
the configured host-key verification policy.

Limits remain server-enforced: five connection tests per normalized
endpoint/profile per minute, five terminal opens per device per minute, three
authentication failures per endpoint/profile causing a 60-second cooldown,
`MAX_DEVICE_CONNECTIONS` globally, three SSH connections per device, and three
terminal sessions globally and per device. Terminal input is capped at 4 KiB,
output at 2 MiB, idle at 15 minutes, and a session at 60 minutes.
`SSH_CONNECT_TIMEOUT_SECONDS` bounds the complete SSH open and defaults to 10
seconds; `TERMINAL_PTY_TIMEOUT_SECONDS` separately bounds PTY and shell creation
and defaults to 10 seconds. Redis permits have a bounded
`CONNECTION_PERMIT_TTL_SECONDS`, default 3900 seconds, which configuration
validation requires to cover the SSH-open, PTY/shell, and maximum-session
timeouts. Uvicorn rejects WebSocket frames larger than the configured 8192-byte
(8 KiB) `--ws-max-size` before application JSON decoding. These current,
configurable limits fail closed where documented, but do not make either SSH or
USB Direct Mode read-only; both can change hardware.

The Telnet console for lab devices is a third Direct Mode path, and the weakest
one. It is unencrypted and presents no host key, so the mandatory SSH host-key
pin does not apply and anyone on the path can read the session, including
anything the operator types. Because of that, Terraformer never decrypts or
sends the stored credential profile over Telnet — the operator types
credentials into the session, as on a console cable.

Three conditions are all required, and are checked before any socket is opened:
the server sets `TELNET_ENABLED` (default off), the device is explicitly marked
as a lab device, and the operator confirms the cleartext warning for that
session. Structured reads always use SSH and fail closed on a Telnet-only node.
Telnet is intended for isolated GNS3/EVE-NG labs and must not be used on a
management network that carries real device credentials.

Lab devices may also re-pin their SSH host key in place, because GNS3/EVE-NG
nodes regenerate it on every restart. That is refused for any device not marked
as a lab device: on real hardware a changed host key is indistinguishable from a
man-in-the-middle and still requires delete and re-registration.

Manual USB Console is also a Direct Mode path. On same-machine Chrome or Edge,
the browser connects directly to an operator-selected USB-to-console adapter;
serial bytes bypass the backend, audit pipeline, credentials, device locks,
snapshots, validation, and rollback controls. Typed or pasted commands can
modify, restart, or erase hardware. Before each fresh session, the operator must
acknowledge that they are authorized and understand this risk, then separately
approve the browser permission chooser. This acknowledgement is not persisted
and is not proof of authorization.

USB Direct Mode requires a secure HTTPS or localhost context and
`Permissions-Policy: serial=(self)`. It stores and reports no selected port,
adapter identifier, settings, command, terminal output, raw exception, or
session history; it creates no telemetry or backend traffic. Multiline input is
held in memory until separately confirmed. Input is bounded to 4 KiB per UTF-8
chunk and 64 KiB pending, but those resource limits do not make commands safe.
User disconnect, navigation, I/O failure, or adapter removal uses ownership-
correct cleanup with a five-second deadline. A later open always creates a fresh
session and reselects an adapter; there is no automatic reconnect, generated
command, vendor template, bootstrap, recording, or recovery path.

## Safety levels

Safety Levels A–D classify structured automation capabilities only. Manual SSH,
Telnet, and USB Direct Mode are outside these levels and can write to or otherwise
change hardware without the structured apply pipeline.

| Level | Meaning | Required UI wording |
|---|---|---|
| A | Native candidate, compare, confirmed commit, and rollback | Native transactional |
| B | Device-assisted rollback or replace for the tested feature | Device-assisted |
| C | Snapshot/diff/post-check; recovery requires connectivity | Best effort; never “auto-rollback” |
| D | Structured write path absent or not lab-verified | Read-only |

A vendor or OS version remains Level D for a structured capability until that
exact capability has sanitized fixtures and real-lab evidence. Evidence for one
command family does not imply support for another.

## Future mandatory apply pipeline

No stage may be skipped when structured writes are introduced in a later phase:

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
- First contact may inspect only the selected endpoint's public SSH host key.
  Every authenticated connection uses the explicitly confirmed per-device pin;
  there is no relaxed global mode and changed keys always fail closed.
- Keep connection establishment (`SSH_CONNECT_TIMEOUT_SECONDS`, default 10) and
  command execution (`SSH_COMMAND_TIMEOUT_SECONDS`, default 30) as separate,
  bounded timeouts. A command timeout must not trigger an unbounded reconnect.
- Structured-write tests in future phases require a current backup, console/OOB
  recovery, an approved maintenance window, and a separately documented
  change/recovery plan.

## Logging and audit

Structured logs and events must contain identifiers, timing, status, error
classifications, and hashes—not credentials or raw secret-bearing output. A
sanitizer is defense in depth; code must avoid sending sensitive values to the
logger in the first place. Any downloaded output must be sanitized and clearly
labelled as observed or inferred.
