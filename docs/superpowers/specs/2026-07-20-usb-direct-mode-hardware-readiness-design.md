# Manual USB Console and Hardware Readiness Design

Date: 2026-07-20
Status: Approved for implementation (frozen)

## Context

Terraformer currently supports registered-device SSH connections, structured
read-only collection, allowlisted diagnostics, and a warning-gated SSH Direct
Mode terminal. The next slice adds a standalone browser-to-serial console for
initial device access and re-verifies the existing application for later,
explicitly authorized hardware validation.

The new feature is **Manual USB Console** or **USB Direct Mode**. It is not a
read-only capability: commands typed or pasted by an operator can modify,
restart, erase, or otherwise disrupt the connected device. Structured device
write capabilities remain Not Implemented and Safety Level D.

## Goals

- Open a USB-to-console serial session before any device is registered.
- Use the browser's Web Serial API on same-machine Chrome or Edge without
  passing host USB devices into Docker.
- Share terminal presentation and lifecycle behavior with the existing SSH
  terminal while keeping SSH WebSocket and USB Serial transports fully
  separate.
- Make serial settings usable with real network hardware: baud presets,
  validated custom baud, configurable line endings, and optional local echo.
- Require an explicit, per-session acknowledgement that the operator is
  authorized to access the attached hardware and understands the Direct Mode
  risk.
- Deterministically clean up permission, I/O, navigation, teardown, and
  unexpected-removal paths; when browser or operating-system cleanup hangs,
  report the timeout and never reuse the old session.
- Leave automated verification and operator documentation ready for a later,
  explicitly authorized hardware validation.

## Non-goals

- Generated configuration or vendor templates.
- Automated command execution or starter-configuration delivery.
- Console bootstrap workflows.
- Structured device writes, configuration apply, rollback, or recovery claims.
- Vendor-specific firewall support.
- Browser-independent serial access, a native helper, or backend serial access.
- Serial-device discovery, auto-reconnect, terminal recording, or session
  persistence.

Console bootstrap is a separate write-capability project. Its first design may
cover Cisco switch and router onboarding only after the read-only structured
paths have authorized lab evidence and the write-safety requirements receive a
separate review. Firewall bootstrap requires its own vendor-specific design.

## Runtime boundary

The browser communicates directly with the operator-selected adapter through
`navigator.serial`. Serial bytes never pass through the API, worker, Redis,
PostgreSQL, Nginx WebSocket proxy, or SSH driver stack. The backend device model
and credential model remain unchanged.

Web Serial is enabled only when all runtime checks pass:

- the document is a secure context;
- `navigator.serial` is available; and
- the page is allowed by `Permissions-Policy: serial=(self)`.

The normal loopback deployment remains supported. Any broader LAN exposure
must use HTTPS in addition to the existing safety review. Unsupported browsers,
insecure contexts, and policy denial produce actionable sanitized UI states.

## Components

### Shared terminal/session layer

The shared layer owns UI-level resources only:

- xterm and its fit/resize integration;
- terminal status and presentation;
- Direct Mode confirmation state;
- line-ending and local-echo policy;
- pending multiline-paste content held in memory;
- resize observers and session-level event listeners; and
- coordination of transport startup and top-level shutdown.

It does not own raw serial bytes, decoder state, serial readers or writers,
stream locks, the serial port, or adapter-disconnect listeners.

### SSH WebSocket transport

`SshWebSocketTransport` owns the existing authenticated WebSocket, Direct Mode
acknowledgement protocol, server messages, resize messages, and socket cleanup.
Its behavior and backend endpoint remain unchanged. Refactoring moves only the
shared terminal/session responsibilities out of the current SSH-specific React
component.

### USB Serial transport

`UsbSerialTransport` exclusively owns:

- the user-approved `SerialPort` reference;
- permission request and port opening;
- raw byte reads and queued writes;
- a write queue capped at 64 KiB of pending UTF-8 input, with each queued input
  chunk capped at 4 KiB;
- incremental `TextDecoder` state, including split multibyte sequences;
- reader and writer objects and their locks;
- read/write failure handling;
- the adapter-disconnect listener; and
- serial-specific buffers and references.

Its public contract supports opening from an explicit user gesture, writing a
validated input chunk with backpressure, publishing decoded output and
sanitized status events, and an idempotent asynchronous `close()`.

The transport rejects an entire new input chunk before transmission when that
chunk would exceed either write bound. It maps the rejection to `serial write
queue full`, blocks further input, and begins normal cleanup. It never silently
drops, truncates, or partially enqueues the rejected chunk.

## User flow

1. The Inventory UI exposes **Open USB Console** even when no device exists.
2. The operator chooses serial settings. Baud presets include common network
   console rates and allow a validated positive custom baud rate. Defaults are
   9600 baud, 8 data bits, 1 stop bit, no parity, and no flow control.
3. The operator chooses `CR`, `LF`, or `CRLF` line endings and may enable local
   echo; local echo is off by default.
4. Before browser permission is requested, the UI warns that USB Direct Mode
   sends commands exactly as entered and can modify, restart, or erase hardware.
   The operator must explicitly acknowledge for this session that they are
   authorized to access the attached hardware and understand those risks. The
   acknowledgement is not persisted and is not treated as proof of permission.
5. After acknowledgement, a separate user gesture calls `requestPort()` and
   opens the selected adapter.
6. Device output is decoded incrementally and written only to the in-memory
   xterm session. Operator input is normalized to the selected line ending and
   sent with stream backpressure.
7. Newlines are first normalized by converting `CRLF` and lone `CR` to canonical
   `LF`. Logical-line detection ignores one trailing empty segment caused by a
   final newline and otherwise counts blank or non-blank segments. Input with
   more than one logical line is held in a UI-only buffer. The UI warns before
   transmission and reports only the line count. Send converts canonical `LF`
   to the selected line ending and transmits the buffered input; cancel discards
   it. This prevents mixed newline forms from bypassing multiline detection.
8. Closing, navigating away, losing the adapter, or encountering an I/O failure
   invokes the shared shutdown path.

No selected port, adapter identifier, settings, input, output, errors, or
terminal history is persisted. A new page/session begins with defaults and
requires a new operator action.

## State and lifecycle

Browser capability is independent of connection state. `unavailable` describes
an unsupported browser, insecure context, or blocked policy; it is not part of
the connection sequence.

The connection sequence is:

```text
idle -> requesting-permission -> opening -> connected -> closing -> idle
           |                    |              |
           +--------------------+--------------+
                    failure or cancellation
```

User cancellation of the port chooser returns to `idle`. A component which has
been permanently unmounted may use an internal `disposed` state to reject late
callbacks. A normal close returns to `idle` so another manual session can be
opened. Failures also clean up and return the connection to `idle`; a sanitized
in-memory UI error may remain visible independently of connection state. There
is no automatic reconnection.

Returning to `idle` never reuses a prior session. Each manual reopen constructs
a fresh shared session, xterm instance, transport instance, decoder, streams,
listeners, and buffers. Disposed instances reject late callbacks and cannot be
reconnected.

### Top-level shutdown

One idempotent top-level shutdown operation handles user disconnect, route or
component changes, open/read/write failures, and unexpected adapter removal:

1. The shared session blocks new UI input and clears any pending confirmation
   or multiline-paste buffer.
2. The active transport's idempotent `close()` runs.
3. The shared session disposes xterm, fit/resize resources, observers, and
   session-level listeners, then renders the appropriate idle or sanitized
   error state if the component remains mounted.

Repeated shutdown calls share or await the same in-flight cleanup and do not
double-release resources. Route changes and unmounts invoke shutdown; document
teardown also receives best-effort cleanup without relying on asynchronous work
to delay navigation.

Top-level shutdown has a five-second deadline. Cleanup still attempts every
ownership-correct step when cancellation or port close fails. If the deadline
expires, the old session is permanently disposed, all owned references and
listeners are cleared, and the UI shows the sanitized `cleanup timed out` state.
A later attempt must create a fresh session and reselect the adapter; if the
browser or operating system still holds the port, opening maps to `port
unavailable` rather than reusing the timed-out transport.

### USB transport cleanup

`UsbSerialTransport.close()` cleans up serial resources only. It:

1. blocks new writes and marks closing;
2. removes the adapter-disconnect listener;
3. cancels the active reader/read loop and releases the reader lock;
4. settles or aborts in-flight writes and releases the writer lock;
5. closes the port when it is still available;
6. clears decoder state, raw byte/write buffers, and serial references; and
7. completes even when cancellation or individual cleanup operations fail.

Each awaited serial cleanup operation is bounded by the remaining top-level
deadline and runs through `finally`-style continuation, so one hung cancellation
or close call does not prevent later release attempts and reference cleanup.

Unexpected adapter removal uses this same path. It reports `device
disconnected` in memory and does not attempt to reopen the port.

## Error mapping and privacy

Raw browser exceptions are never displayed, persisted, transmitted, logged, or
sent to backend error reporting. They are mapped in memory to one of these
operator-facing states:

- browser unsupported;
- secure context required;
- serial access blocked by policy;
- permission denied;
- port unavailable or already in use;
- device disconnected;
- serial read failed;
- serial write failed;
- serial write queue full; or
- cleanup timed out.

The feature must not use `localStorage`, `sessionStorage`, IndexedDB, terminal
history, analytics, telemetry, backend REST calls, backend WebSockets, or error
reporting. Error paths have the same prohibition. Xterm scrollback and pending
paste exist only in memory and are destroyed during shared session teardown.

## Automated verification

All serial tests use fake Web Serial ports and streams. They do not enumerate,
open, read, or write any real hardware. Coverage includes:

- unavailable API, insecure context, policy denial, permission denial, and
  cancelled chooser states;
- baud presets, valid/invalid custom baud, fixed 8N1/no-flow settings, line
  ending normalization, and local echo;
- partial reads and split multibyte decoding across chunks;
- successful reads and writes with backpressure;
- 4 KiB per-chunk and 64 KiB pending-write bounds, including whole-chunk
  rejection without silent truncation or partial enqueue;
- read failure, write failure, and cancellation while cleanup is active;
- adapter removal while a read or write is active;
- multiline-paste hold, warning, send/cancel behavior, and buffer clearing after
  send, cancellation, failure, disconnect, route change, and teardown;
- idempotent transport cleanup and independently owned shared-session cleanup;
- the five-second cleanup deadline, late callback rejection, and fresh
  session/transport/xterm recreation after normal close, failure, and timeout;
- listener, observer, xterm, buffer, reader, writer, lock, and port disposal;
- a standalone USB Console entry before device registration;
- SSH terminal regression behavior through its separate WebSocket transport;
  and
- zero backend REST or WebSocket traffic from USB Direct Mode, including every
  tested error path.

Storage and network primitives are spied or stubbed in regression tests so an
unexpected persistence or backend call fails the suite.

## Project readiness verification

Before handoff, run the relevant frontend and backend format, lint, type, test,
and production-build checks. Validate normal and development Compose files,
build the affected images, confirm the Nginx Permissions Policy response header,
confirm the same `Permissions-Policy: serial=(self)` header from the frontend
development server, and run local application health checks. Automated header
checks cover both production and development serving paths. These checks must
not contact a network device.

Refactoring is limited to the terminal/session seam and readiness blockers
found by these checks. Existing device drivers, structured SSH reads, discovery,
diagnostics, snapshots, credential handling, and database models are not
redesigned for the USB feature.

## Documentation and status

Update architecture, safety, user, lab-test, implementation-status, and
capability-matrix documentation. All user-facing text calls the feature
**Manual USB Console** or **USB Direct Mode** and states that operator commands
can change hardware. It must not be described as read-only.

Documentation reports two independent states:

- **Automated verification passed** when fake-stream tests and project checks
  pass.
- **Hardware validation pending** until an explicitly authorized real-adapter
  session is completed.

Implementation without authorized hardware evidence remains lab unverified.
The capability matrix records USB Direct Mode separately from structured read
and write capabilities because it is an operator-controlled escape hatch, not a
driver capability.

An authorized hardware-validation record contains validation metadata only:

- date;
- approver;
- browser and version;
- adapter type;
- device category;
- application version or commit;
- validation steps as non-command descriptions; and
- pass/fail outcome.

It must not retain terminal output, commands, credentials, configurations,
device identifiers, or any other serial-session content.

## Acceptance criteria

- A supported same-machine browser can open USB Direct Mode before registration
  after explicit operator-authorization/device-change acknowledgement and
  browser permission, with acknowledgement required again for every fresh
  session.
- Serial settings, input policy, output decoding, local echo, and multiline
  paste confirmation behave as specified, including normalized multiline
  detection and bounded whole-chunk write queuing.
- All normal and exceptional exits use the idempotent ownership-correct cleanup
  path and leave no active port, stream lock, listener, observer, xterm instance,
  or pending paste buffer within the cleanup deadline, or permanently dispose
  the old session and report a sanitized cleanup-timeout state.
- Every reopen uses newly constructed session, transport, decoder, stream,
  listener, buffer, and xterm objects.
- USB Direct Mode creates no persisted state and no backend REST or WebSocket
  traffic.
- Existing SSH Direct Mode and structured read-only workflows pass regression
  verification unchanged.
- Secure-context and Permissions Policy requirements are enforced and
  documented, with the required header verified in both production and
  development serving paths.
- Automated verification is recorded separately from hardware validation, and
  the feature remains lab unverified without explicit authorized evidence.
