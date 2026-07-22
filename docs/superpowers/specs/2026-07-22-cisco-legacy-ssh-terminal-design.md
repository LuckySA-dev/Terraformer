# Cisco Legacy SSH Compatibility and Device Terminal UI Design

Date: 2026-07-22
Status: Approved

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
- `docs/network-automation-final-plan.md` remains unchanged.

## Compatibility model

Each device has one `ssh_compatibility` value:

- `modern` is the default for new and migrated devices and supplies no legacy
  algorithm overrides.
- `cisco_legacy` appends the approved Cisco compatibility set after modern defaults.
- `cisco_legacy_group1` appends the same set plus
  `diffie-hellman-group1-sha1` as an explicit last resort.

The selection is available before persistence in Add Device, discovery approval, and
explicit connection-test requests. After persistence it is device-scoped and editable.
Changing the selection invalidates the previous connection-test result, so the device
cannot be saved again until the operator runs another explicit test.

Discovery never selects or escalates a compatibility mode. Credential profiles remain
transport-neutral and store no compatibility setting. A Legacy badge is displayed for
saved legacy devices, and the group1 option requires a stronger warning describing it
as a last-resort per-device exception.

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

## Components and data flow

The device API model and database record carry the compatibility value. A migration
sets every existing device to `modern`. The request model also carries the value for
pre-save tests and discovery approval.

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

## Host-key verification

Compatibility mode does not weaken or bypass the configured host-key policy. In strict
mode, an unknown or changed host key fails. The existing loopback lab default may run
with strict verification disabled only through its documented operator setting; Legacy
mode does not change that setting, trust a key, replace a key, or ignore a mismatch.

Mandatory host-key enrollment or pinning is a separate future security slice and is not
silently added here.

## Lifecycle and sanitized errors

Each connection remains request- or session-scoped. Compatibility options are built
immediately before opening the selected device connection and are discarded during the
existing transport or terminal cleanup path.

Failures are classified in memory by phase:

1. TCP connection
2. SSH negotiation
3. host-key verification
4. authentication
5. PTY creation
6. terminal I/O or disconnection

The UI, audit records, RQ failure data, and application logs receive only stable,
sanitized result codes and messages. They never receive credentials, terminal content,
commands, raw exceptions, exception chains, peer-offered algorithm lists, or the
negotiated algorithm. Safe audit metadata may contain the device identifier, actor,
timestamp, requested compatibility mode, group1 state, failure phase, and sanitized
result code. It must not claim which algorithm was negotiated.

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
compact message with a Retry action which starts a fresh connection attempt; it never
reveals a backend exception.

Terminal tabs retain the three-session limit. Their selected state, focus state, close
control, and hit targets remain keyboard-accessible and visually clear. No terminal
buffer, command, output, or session error is persisted to browser storage, analytics,
telemetry, or backend error reporting.

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
- migration, API validation, persistence, pre-save requests, and discovery approval
  default to `modern`;
- changing compatibility invalidates an earlier successful connection test;
- discovery never enables Legacy mode automatically;
- every connection phase maps to sanitized output and raw values cannot reach UI,
  audit, logs, or persisted job failures.

Frontend coverage verifies:

- Add, Edit, and discovery approval submit the selected compatibility mode and display
  the required warnings and badges;
- changing the mode disables Save until a new explicit test succeeds;
- the Terminal tab applies the desktop width modifier, responsive layout, readable
  status, retry state, and accessible tabs;
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
