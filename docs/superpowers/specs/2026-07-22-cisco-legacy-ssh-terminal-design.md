# Cisco Legacy SSH Compatibility and Device Terminal UI Design

Date: 2026-07-22
Status: Approved, including the security-critical revision

## Problem

Authorized lab validation showed that structured SSH reads can reach and authenticate
to an end-of-support Cisco Catalyst device after transport hardening, while the device
terminal still fails after its WebSocket is accepted. The structured path uses
Scrapli's system OpenSSH transport, but the terminal opens a separate AsyncSSH session.
These transports currently have no shared, explicit per-device compatibility policy.

The terminal is also constrained by the inspector's fixed 374 px column. Its Direct
Mode warning, connection state, error message, tabs, and xterm canvas compete for a
small area, making failures hard to understand and successful sessions unnecessarily
cramped.

## Goals

- Support explicitly selected, end-of-support Cisco SSH implementations without
  weakening global SSH defaults.
- Apply the same device compatibility selection to structured Scrapli connections and
  AsyncSSH terminal connections.
- Keep modern algorithms preferred and legacy algorithms request- or device-scoped.
- Attempt only the selected credential profile's password authentication method.
- Preserve the configured host-key verification policy and sanitize every error path.
- Bound authentication attempts, concurrent connections, and terminal resources on the
  backend so reconnects and worker jobs cannot bypass the limits.
- Make the existing device terminal usable in the inspector without introducing a new
  terminal implementation.
- Keep routine verification network-free and support claims conservative until an
  authorized hardware result is recorded.

## Non-goals

- No automatic legacy fallback, global SSH configuration change, algorithm discovery,
  peer-offered algorithm recording, or automatic device classification.
- No SSH agent, local-key, PKCS#11, GSS, host-based, public-key, or unrequested
  keyboard-interactive authentication.
- No Telnet, FTP, vendor template, generated command, bootstrap workflow, automatic
  command execution, or structured write capability.
- No topology configuration action, graph-driven device change, pop-out terminal,
  resizable inspector, or terminal-session persistence.
- No mandatory host-key enrollment workflow in this slice. Existing strict and local
  lab host-key settings retain their documented behavior.
- No multi-user identity, role-based access control, dedicated legacy permission names,
  one-time terminal authorization-token service, live cross-tab session revocation, or
  active-session registry is added to this single-user local application.
- No destination-CIDR administration or complete DNS-rebinding/SSRF policy is added.
  Exact-target validation remains mandatory, and a broader destination policy requires
  a separate design which preserves approved RFC1918 management access.
- No telemetry, tracing, or crash-reporting service is introduced. If one is added
  later, the existing secret and terminal-content exclusions apply before enablement.
- `docs/network-automation-final-plan.md` remains unchanged.

## Compatibility model

Each device has one `ssh_compatibility` value:

- `modern` is the default for new and migrated devices and supplies no legacy
  algorithm overrides.
- `cisco_legacy` appends the approved Cisco compatibility set after modern defaults.
- `cisco_legacy_group1` appends the same set plus
  `diffie-hellman-group1-sha1` as an explicit last resort.

The exact mapping and connection behavior in this document is
`compatibility_policy_version = 1`. Changing the algorithm set or ordering,
authentication behavior, or Group1 handling requires a new version and renewed
automated and hardware verification. Evidence for one version is not presented as
evidence for a materially different version.

The selection is available before persistence in Add Device, discovery approval, and
explicit connection-test requests. After persistence it is device-scoped and editable.
Changing the selection invalidates the previous connection-test result, so the device
cannot be saved again until the operator runs another explicit test.

Discovery never selects or escalates a compatibility mode. Credential profiles remain
transport-neutral and store no compatibility setting. A Legacy badge is displayed for
saved legacy devices, and the group1 option requires a stronger warning describing it
as a last-resort per-device exception. Enabling, pre-save testing, discovery approval,
or terminal use of Group1 requires an explicit Group1-risk acknowledgment which the
backend validates. The acknowledgment is audit metadata, not a reusable permission or
a substitute for the server policy gate.

## Approved algorithm policy

Modern defaults always remain first. `cisco_legacy` appends only:

- key exchange: `diffie-hellman-group14-sha1`, then
  `diffie-hellman-group-exchange-sha1`;
- host-key signature: `ssh-rsa`, while RSA SHA-2 signatures remain preferred;
- ciphers: `aes256-cbc`, `aes192-cbc`, `aes128-cbc`;
- MACs: `hmac-sha1`, `hmac-sha1-96`.

`cisco_legacy_group1` additionally appends
`diffie-hellman-group1-sha1`. `ssh-dss`, MD5-based algorithms, 3DES, and RC4 remain
disabled in every mode.

The policy is additive rather than a replacement list. It never changes process-wide
OpenSSH configuration, AsyncSSH defaults, another device, or a later connection. A
modern failure returns a sanitized result and never retries in a legacy mode.

## Server policy and authorization boundary

Every API and terminal entry point continues to require the authenticated local-admin
session. This deployment has no distinct users, actors, roles, or permission grants, so
it does not introduce permission names which would provide no real isolation.

Three server-controlled settings provide the enforceable operational boundary:

- `SSH_LEGACY_ENABLED`, default `false`;
- `SSH_GROUP1_ENABLED`, default `false`;
- `SSH_TERMINAL_ENABLED`, default `true` to preserve the existing local deployment.

They are evaluated immediately before every connection, including pre-save tests,
device create/update tests, discovery approval, structured API and worker connections,
and terminal WebSocket sessions. A disabled selection fails closed with a stable
sanitized policy code. It never changes the saved device or falls back to another mode.
Frontend visibility is not an authorization boundary.

Safe audit metadata identifies the existing principal as `local-admin`; it must not be
represented as a distinct human identity. A future multi-user or externally exposed
deployment requires a separate RBAC and session-revocation design before introducing
dedicated permissions such as `device:ssh_legacy`.

## Components and data flow

The device API model and database record carry the compatibility value. A migration
sets every existing device to `modern`. The request model also carries the value for
pre-save tests and discovery approval.

The backend never trusts a prior browser connection-test result as authorization to
save. Device create and security-relevant update requests perform a fresh connection
test using the submitted normalized endpoint, resolved port, credential-profile ID,
host-key setting, compatibility mode, policy version, and transport category. Changing
any connection-relevant field, including compatibility mode, therefore causes a fresh
test in the same backend operation. No password, secret-derived binding, reusable test
grant, or test token is stored.

`ConnectionParameters` carries the normalized value to the transport boundary. One
small, side-effect-free compatibility policy maps that value to transport-specific
options:

- Scrapli's system transport receives request-scoped OpenSSH options;
- AsyncSSH receives equivalent request-scoped algorithm lists and authentication
  settings.

The existing Scrapli structured-read path and AsyncSSH terminal path remain separate
transport implementations. They consume the same policy value but do not share live
connections, byte queues, PTY state, readers, writers, decoders, or cleanup state.

For password profiles, both paths make one password-authentication attempt with the
explicitly selected username and password. OpenSSH is configured to ignore the SSH
agent and local identities, prefer password authentication only, and allow one password
prompt. AsyncSSH ignores user SSH configuration, local keys, and the agent, and enables
only password authentication. Keyboard-interactive support requires a future explicit
credential-profile authentication method; it is not a fallback in this slice.

Queue payloads carry only existing opaque job and device identifiers. Credentials are
resolved and decrypted just in time at the trusted connection boundary and are never
placed in queue arguments or metadata, subprocess command-line arguments, environment
variables, temporary files, URLs, WebSocket messages, audit details, traces, or retained
worker exceptions. References are released during every cleanup path. The design does
not claim secure zeroization of immutable Python strings.

## Host-key verification

Compatibility mode does not weaken or bypass the configured host-key policy. In strict
mode, an unknown or changed host key fails. The existing loopback lab default may run
with strict verification disabled only through its documented operator setting; Legacy
mode does not change that setting, trust a key, replace a key, or ignore a mismatch.

Mandatory host-key enrollment or pinning is a separate future security slice and is not
silently added here.

## Authentication and resource limits

The existing Redis service provides one shared, expiring connection gate for API,
worker, and terminal paths. It stores counters and permit identifiers only, never
credentials or terminal content. The single-user principal is `local-admin`.

Initial defaults are deliberately small and configurable:

- five connection-test attempts per normalized endpoint and credential profile per
  minute;
- five terminal-open attempts per device per minute;
- three authentication failures for the same endpoint and credential profile within a
  minute trigger a 60-second cooldown;
- at most `MAX_DEVICE_CONNECTIONS` concurrent SSH connections globally;
- at most three concurrent SSH connections per device;
- at most three terminal sessions globally and per device.

Keys for pre-save endpoints use a one-way digest of the normalized endpoint and profile
identifier. A new WebSocket, API request, worker execution, retry, or process cannot
bypass an active Redis cooldown. Authentication success clears that tuple's failure
counter. Negotiation, host-key, PTY, and ordinary network failures do not increment the
authentication-failure counter. Redis unavailability fails connection admission closed
with a sanitized service-unavailable result. Every permit has a bounded TTL so process
termination cannot leak capacity indefinitely.

The existing SSH connect timeout bounds TCP, negotiation, host-key verification, and
authentication as one open operation. PTY and shell creation receive a separate
10-second timeout. Terminal input idle timeout remains 15 minutes, maximum session
duration is 60 minutes, a decoded inbound terminal message is capped at 4 KiB, and
session output remains capped at 2 MiB. Uvicorn's WebSocket frame limit is set to 8 KiB
for defense before JSON decoding.

The relay retains one sequential read-and-send path: it does not read the next SSH
chunk until the previous WebSocket send completes. Combined with the SSH channel's
flow control and existing 4 KiB chunks, this provides slow-client backpressure without
adding an application queue. No unbounded pending-input or output queue is introduced.
Limit failures use stable sanitized codes.

## Lifecycle and sanitized errors

Each connection remains request- or session-scoped. Compatibility options are built
immediately before opening the selected device connection and are discarded during the
existing transport or terminal cleanup path. Cleanup is idempotent and stops accepting
input before cancelling relay tasks, closing the SSH channel and connection, closing
the WebSocket, releasing Redis and in-process permits, discarding compatibility
options, and releasing credential references. Delayed writes and reconnect callbacks
carry a disposed-session guard and cannot revive a closed session.

The same cleanup path runs after normal close, tab removal, component teardown, route
change, page hide or refresh, WebSocket disconnect, every connection phase failure,
idle or maximum-duration timeout, device disconnect, relay cancellation, and process
shutdown. Pending paste and input buffers are cleared before transport cleanup. Raw
cleanup exceptions are discarded after mapping to a sanitized cleanup result.

This slice cannot guarantee immediate server-side closure when logout occurs in a
different tab, access is revoked, a device is deleted, or a credential is rotated:
current signed sessions are stateless and there is no revocation-aware active-session
registry. The current UI teardown still closes its own session, database foreign keys
still prevent deletion of an assigned credential profile, and all newly opened
connections resolve current device and credential records. Cross-tab revocation is a
separate multi-user/session architecture slice.

Failures are classified in memory by phase:

1. TCP connection
2. SSH negotiation
3. host-key verification
4. authentication
5. PTY creation
6. terminal I/O or disconnection

Every sanitized error contains a stable `code`, `phase`, `retryable` boolean, and an
optional fixed-catalog `recommended_action`. Timeouts, temporary connection loss,
expired sessions, and released session capacity may be retryable. Authentication
rejection, host-key failure, negotiation failure, PTY or shell rejection, policy denial,
and active cooldown are not automatically retryable. Authentication errors never reveal
whether the username or password was incorrect. A retry always creates a new admitted
connection and never reuses SSH or authentication state.

Stable codes include `device_connection_timeout`, `device_connection_refused`,
`device_connection_lost`, `device_name_resolution_failed`, `device_host_key_unknown`,
`device_host_key_changed`, `legacy_ssh_negotiation_failed`,
`legacy_mode_disabled_by_policy`, `legacy_group1_disabled_by_policy`,
`device_authentication_failed`, `device_authentication_rate_limited`,
`terminal_pty_rejected`, `terminal_shell_rejected`,
`terminal_session_limit_reached`, `terminal_idle_timeout`,
`terminal_session_expired`, and `terminal_transport_failed`.

The UI, audit records, RQ failure data, and application logs receive only those stable,
sanitized fields. They never receive credentials, terminal content, commands, raw
exceptions, exception chains, library exception names or messages, peer-offered
algorithm lists, or the negotiated algorithm. Safe audit metadata may contain the
`local-admin` principal, internal device identifier, timestamp, requested compatibility
mode, Group1 state, compatibility-policy version, operation category, failure phase,
authorization decision, bounded session duration, and sanitized result code. It must
not claim which algorithm was negotiated or retain unnecessary addresses or hostnames.

## Device terminal UI

The existing `TerminalPanel`, shared `TerminalSession`, xterm integration, and SSH
WebSocket transport remain in place. USB Direct Mode keeps its existing layout and
ownership boundaries.

When the Terminal inspector tab is active above the 1020 px drawer breakpoint, the
workspace uses a terminal modifier which expands the inspector from 374 px to 680 px,
capped at 48 percent of the viewport, while allowing the inventory column to shrink
without horizontal page overflow. At or below 1020 px, the terminal drawer width is
`min(680px, calc(100vw - 74px))`; non-terminal inspector tabs retain their current
widths.

The xterm canvas replaces its fixed 310 px height with
`clamp(360px, 55vh, 620px)`. The Direct Mode warning stays visible and mandatory but
uses a compact layout. The session status clearly shows
`Idle`, `Connecting`, `Connected`, or `Disconnected`. A sanitized failure appears as a
compact message. Retry appears only when the backend marks the result retryable and
always starts a fresh connection attempt. Non-retryable authentication, host-key,
negotiation, PTY, shell, and policy failures show their fixed safe recommended action
without a generic Retry control.

Terminal tabs retain the three-session limit. Their selected state, focus state, close
control, and hit targets remain keyboard-accessible and visually clear. No terminal
buffer, command, output, or session error is persisted to browser storage, analytics,
telemetry, or backend error reporting.

SSH Direct Mode uses the shared input-policy and UI confirmation buffer already used by
USB Direct Mode. A paste requires confirmation when it contains more than one normalized
line, exceeds 1,024 characters, or contains control characters other than horizontal
tab, carriage return, or line feed. The confirmation displays only line and character
counts. At most 4 KiB of pending UTF-8 input is accepted. Cancellation, send completion,
failure, retry, tab switch, route change, disconnect, and teardown clear the buffer; no
buffered input is resent after reconnect.

Device output is untrusted. xterm explicitly keeps proposed APIs and window operations
disabled, sets its OSC link handler to `null`, and does not load clipboard, download,
notification, or web-link addons or register custom OSC handlers. The application does
not consume remote title-change events. Output therefore cannot open a URL, update the
application title, access the clipboard, download a file, notify the browser, or invoke
an application action. Any future link support requires a separate user-gesture and
scheme-validation design.

## Verification

Routine tests use fakes and must create no device, backend-external, or lab-network
traffic.

Backend coverage verifies:

- `modern` supplies no legacy algorithm options;
- `cisco_legacy` and `cisco_legacy_group1` produce the exact approved additive policy
  for both OpenSSH and AsyncSSH;
- group1 is absent from the base legacy mode and all prohibited algorithms remain
  absent;
- agent, local-key, SSH-config, alternate authentication, and automatic retry paths are
  disabled;
- policy version and all three server kill switches fail closed at every synchronous,
  worker, and terminal connection boundary without mutating the saved device;
- Group1 use without the explicit acknowledgment is rejected by the backend;
- migration, API validation, persistence, pre-save requests, and discovery approval
  default to `modern`;
- create and security-relevant update operations perform a fresh backend test, and a
  compatibility change cannot reuse a prior browser result;
- discovery never enables Legacy mode automatically;
- retryability and recommended actions are determined by sanitized failure type;
- Redis admission, cooldown, global/per-device concurrency, TTL recovery, and process
  or reconnect bypass attempts fail as designed without retaining target plaintext;
- queue payloads, subprocess arguments, environment, temporary files, logs, audit,
  WebSocket messages, and persisted failures contain no credential material;
- TCP/SSH open, PTY, idle, maximum duration, frame/input/output, and slow-client limits
  are backend-enforced;
- cleanup is idempotent across success, failure, cancellation, timeout, disconnect, and
  shutdown; and
- every connection phase maps to sanitized output and prohibited raw values cannot
  reach UI, audit, logs, or persisted job failures.

Frontend coverage verifies:

- Add, Edit, and discovery approval submit the selected compatibility mode and display
  the required warnings and badges;
- Group1 requires its stronger acknowledgment and disabled policies remain understandable;
- changing the mode disables Save until a new explicit test succeeds;
- the Terminal tab applies the desktop width modifier, responsive layout, readable
  status, retry state, and accessible tabs;
- non-retryable failures do not show Retry, while retryable failures create a fresh
  transport;
- multiline, large, and unsafe-control-character paste requires confirmation, and
  pending input is never resent after retry or teardown;
- xterm output cannot trigger clipboard, download, notification, title, link-opening,
  or privileged application behavior;
- USB Direct Mode retains its existing layout and behavior;
- terminal attempts do not create persistence or telemetry traffic.

Handoff verification runs backend format, lint, types, and tests; frontend typecheck,
lint, tests, and production build; and both Compose configuration checks. Real hardware
validation remains separately opt-in and exact-target. Its repository record may store
only the date, approver, browser, adapter or transport category, device category,
application commit, requested compatibility mode, validation-step descriptions, and
pass/fail result. It must not contain addresses, hostnames, serial numbers, credentials,
commands, terminal output, configuration, screenshots, raw errors, or session content.

## Delivery status

Implementation alone is reported as automated verification passed and hardware
validation pending. Existing structured Cisco evidence may be recorded separately with
sanitized metadata, but the Web SSH terminal and topology portions remain lab-unverified
until their own authorized acceptance criteria pass. Phase 3 structured configuration
work does not begin as part of this slice.
