# Manual USB Console Hardware Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone, browser-native Manual USB Console that is safe to open before device registration, preserves the existing SSH Direct Mode behavior, and leaves the project automatically verified but hardware-validation pending.

**Architecture:** A shared React terminal/session layer owns xterm, confirmations, input policy, UI buffers, and session teardown. `SshWebSocketTransport` and `UsbSerialTransport` implement a narrow transport contract while retaining exclusive ownership of their socket or serial resources. USB bytes remain browser-local; the backend, device model, credentials, and structured driver paths do not change.

**Tech Stack:** React 19, TypeScript 5.9 strict mode, xterm.js 6, Web Serial API, Web Streams, Vitest/Testing Library, Vite 8, Nginx 1.29, Docker Compose.

## Global Constraints

- Preserve `docs/network-automation-final-plan.md` unchanged.
- Never contact, enumerate, open, read, or write real hardware during implementation or automated verification.
- Call the feature **Manual USB Console** or **USB Direct Mode**; never describe it as read-only.
- Keep generated configuration, automated commands, bootstrap flows, vendor templates, and firewall-specific behavior out of scope.
- Keep all structured device write capabilities Not Implemented and Safety Level D.
- Support same-machine Chrome/Edge only when `window.isSecureContext`, `navigator.serial`, and `Permissions-Policy: serial=(self)` permit it.
- Default to 9600 baud, 8 data bits, 1 stop bit, no parity, no flow control, local echo off, and configurable `CR`/`LF`/`CRLF` line endings.
- Cap each USB input chunk at 4 KiB and total pending UTF-8 writes at 64 KiB; reject an overflowing chunk whole.
- Apply a five-second cleanup deadline and create fresh session, transport, xterm, decoder, stream, listener, and buffer objects for every reopen.
- Require a non-persisted operator-authorization/device-change acknowledgement before every permission request.
- Do not use localStorage, sessionStorage, IndexedDB, terminal history, analytics, telemetry, backend REST, backend WebSockets, or backend error reporting from USB Direct Mode, including error paths.
- Never display, persist, transmit, or log raw browser exceptions, commands, terminal output, adapter identifiers, credentials, or serial-session content.
- Preserve unrelated dirty-worktree changes.
- Execute the plan from an isolated feature worktree/branch created by `superpowers:using-git-worktrees`; keep `main` as the fixed regression base for final `detect-changes --scope compare --base-ref main`.
- Before editing an existing function, run `node .gitnexus/run.cjs impact <symbol> --direction upstream --file <path> --kind Function`; warn before continuing if risk is HIGH or CRITICAL.
- Before every commit, stage only that task and run `node .gitnexus/run.cjs detect-changes --scope staged` followed by `git diff --cached --check`.
- Do not add a dependency; use Web Serial, Web Streams, `TextEncoder`, and `TextDecoder` already supplied by the browser.

## File Structure

- Create `frontend/src/features/terminal/transport.ts`: shared transport events, contract, sanitized error type, and fixed limits.
- Create `frontend/src/features/terminal/inputPolicy.ts`: newline normalization, logical-line detection, output line-ending conversion, and baud parsing.
- Create `frontend/src/features/terminal/UsbSerialTransport.ts`: Web Serial types, capability lookup, bounded writes, incremental decoding, adapter events, and serial-only cleanup.
- Create `frontend/src/features/terminal/SshWebSocketTransport.ts`: existing SSH WebSocket protocol and socket-only cleanup.
- Create `frontend/src/features/terminal/TerminalSession.tsx`: shared xterm/session UI, confirmation buffers, input policy, fresh-session construction, and top-level cleanup.
- Create `frontend/src/features/inventory/UsbConsoleDialog.tsx`: standalone settings and USB Direct Mode composition.
- Create `frontend/tests/fakes/webSerial.ts`: reusable fake Web Serial port and native-stream controls for transport and UI tests.
- Modify `frontend/src/features/inventory/TerminalPanel.tsx`: retain tab behavior while delegating a tab to the shared session plus SSH transport.
- Modify `frontend/src/features/inventory/InventoryPage.tsx`: expose USB Console before registration and host its modal.
- Modify `frontend/src/components/AppShell.tsx`, `frontend/src/features/access/AccessGate.tsx`, and `frontend/src/features/inventory/DeviceInspector.tsx`: qualify read-only claims as structured automation rather than Direct Mode.
- Modify `frontend/src/styles.css`: style console settings, authorization, status, and multiline confirmation using existing tokens.
- Modify `frontend/vite.config.ts` and `frontend/nginx.conf`: serve `Permissions-Policy: serial=(self)` in development and production.
- Create `frontend/tests/terminal-input-policy.test.ts`: pure input and baud cases.
- Create `frontend/tests/usb-serial-transport.test.ts`: fake-stream serial transport and cleanup cases.
- Modify `frontend/tests/terminal-panel.test.tsx`: shared-session and SSH regression cases.
- Create `frontend/tests/usb-console-dialog.test.tsx`: UI, capability, authorization, settings, privacy, and no-backend-traffic cases.
- Create `frontend/tests/serving-policy.test.ts`: static regression for both serving configurations.
- Modify `docs/architecture.md`, `docs/safety-model.md`, `docs/user-guide.md`, `docs/lab-test-guide.md`, `docs/IMPLEMENTATION_STATUS.md`, and `docs/CAPABILITY_MATRIX.md`: operator guidance, truthful safety/status language, and metadata-only validation evidence.

---

### Task 1: Terminal Contract and Input Policy

**Files:**
- Create: `frontend/src/features/terminal/transport.ts`
- Create: `frontend/src/features/terminal/inputPolicy.ts`
- Test: `frontend/tests/terminal-input-policy.test.ts`

**Interfaces:**
- Consumes: Browser `Date.now`, `TextEncoder`, and strings emitted by xterm.
- Produces: `TerminalTransport`, `TerminalTransportEvent`, `TerminalTransportError`, `TerminalInputPolicy`, `prepareTerminalInput()`, `parseBaudRate()`, `TERMINAL_CLEANUP_TIMEOUT_MS`, `USB_WRITE_CHUNK_LIMIT_BYTES`, and `USB_WRITE_QUEUE_LIMIT_BYTES`.

- [ ] **Step 1: Write the failing pure-policy tests**

Create `frontend/tests/terminal-input-policy.test.ts` with these exact cases:

```ts
import {
  parseBaudRate,
  prepareTerminalInput,
} from '../src/features/terminal/inputPolicy';

describe('terminal input policy', () => {
  it.each([
    ['show version\r\nshow clock\r\n', 'cr' as const, 'show version\rshow clock\r'],
    ['show version\rshow clock', 'lf' as const, 'show version\nshow clock'],
    ['show version\nshow clock', 'crlf' as const, 'show version\r\nshow clock'],
  ])('normalizes mixed newlines before applying %s output', (input, lineEnding, expected) => {
    expect(prepareTerminalInput(input, { lineEnding, localEcho: false, confirmMultiline: true }))
      .toEqual({ data: expected, lineCount: 2, requiresConfirmation: true });
  });

  it('ignores one final empty segment but counts an intentional blank line', () => {
    expect(prepareTerminalInput('show version\n', {
      lineEnding: 'lf', localEcho: false, confirmMultiline: true,
    }).lineCount).toBe(1);
    expect(prepareTerminalInput('show version\n\n', {
      lineEnding: 'lf', localEcho: false, confirmMultiline: true,
    }).lineCount).toBe(2);
  });

  it('preserves raw SSH input', () => {
    expect(prepareTerminalInput('\r', {
      lineEnding: 'raw', localEcho: false, confirmMultiline: false,
    })).toEqual({ data: '\r', lineCount: 1, requiresConfirmation: false });
  });

  it.each([
    ['9600', 9600],
    ['115200', 115200],
    ['4294967295', 4294967295],
  ])('accepts unsigned-long baud %s', (value, expected) => {
    expect(parseBaudRate(value)).toBe(expected);
  });

  it.each(['', '0', '-1', '1.5', '4294967296', 'not-a-number'])
    ('rejects invalid baud %s', (value) => {
      expect(parseBaudRate(value)).toBeNull();
    });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `frontend/`:

```text
npm test -- --run tests/terminal-input-policy.test.ts
```

Expected: FAIL because `features/terminal/inputPolicy` does not exist.

- [ ] **Step 3: Add the transport contract and fixed limits**

Create `frontend/src/features/terminal/transport.ts` with this public surface:

```ts
export const TERMINAL_CLEANUP_TIMEOUT_MS = 5_000;
export const USB_WRITE_CHUNK_LIMIT_BYTES = 4_096;
export const USB_WRITE_QUEUE_LIMIT_BYTES = 65_536;

export type TerminalStatus = 'connecting' | 'connected' | 'closed';

export type TerminalTransportEvent =
  | { type: 'output'; data: string }
  | { type: 'status'; status: TerminalStatus }
  | { type: 'error'; code: string; message: string };

export type TerminalTransportListener = (event: TerminalTransportEvent) => void;

export interface TerminalTransport {
  readonly kind: 'ssh' | 'usb';
  open(listener: TerminalTransportListener): Promise<void>;
  write(data: string): Promise<void>;
  resize(columns: number, rows: number): void;
  close(deadlineAt: number): Promise<void>;
}

export class TerminalTransportError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = 'TerminalTransportError';
  }
}
```

- [ ] **Step 4: Add normalized input preparation and baud parsing**

Create `frontend/src/features/terminal/inputPolicy.ts`:

```ts
export type LineEnding = 'raw' | 'cr' | 'lf' | 'crlf';

export interface TerminalInputPolicy {
  lineEnding: LineEnding;
  localEcho: boolean;
  confirmMultiline: boolean;
}

export interface PreparedTerminalInput {
  data: string;
  lineCount: number;
  requiresConfirmation: boolean;
}

const outputNewline = { cr: '\r', lf: '\n', crlf: '\r\n' } as const;

export function prepareTerminalInput(
  input: string,
  policy: TerminalInputPolicy,
): PreparedTerminalInput {
  if (policy.lineEnding === 'raw') {
    return { data: input, lineCount: 1, requiresConfirmation: false };
  }
  const normalized = input.replaceAll('\r\n', '\n').replaceAll('\r', '\n');
  const lines = normalized.split('\n');
  if (lines.length > 1 && lines.at(-1) === '') lines.pop();
  const lineCount = Math.max(1, lines.length);
  return {
    data: normalized.replaceAll('\n', outputNewline[policy.lineEnding]),
    lineCount,
    requiresConfirmation: policy.confirmMultiline && lineCount > 1,
  };
}

export function parseBaudRate(value: string): number | null {
  const baudRate = Number(value);
  return Number.isInteger(baudRate) && baudRate > 0 && baudRate <= 0xffff_ffff
    ? baudRate
    : null;
}
```

- [ ] **Step 5: Run focused tests, types, and lint**

Run from `frontend/`:

```text
npm test -- --run tests/terminal-input-policy.test.ts
npm run typecheck
npm run lint
```

Expected: all commands pass.

- [ ] **Step 6: Commit the contract**

```text
git add frontend/src/features/terminal/transport.ts frontend/src/features/terminal/inputPolicy.ts frontend/tests/terminal-input-policy.test.ts
node .gitnexus/run.cjs detect-changes --scope staged
git diff --cached --check
git commit -m "refactor: define terminal transport contract"
```

Expected GitNexus scope: only the new terminal contract/input symbols and their test references; no backend flow.

---

### Task 2: Bounded USB Serial Transport

**Files:**
- Create: `frontend/src/features/terminal/UsbSerialTransport.ts`
- Create: `frontend/tests/fakes/webSerial.ts`
- Test: `frontend/tests/usb-serial-transport.test.ts`

**Interfaces:**
- Consumes: `TerminalTransport`, `TerminalTransportListener`, `TerminalTransportError`, and the three fixed limits from Task 1.
- Produces: `UsbSerialTransport`, `SerialApi`, `SerialPortLike`, `UsbSerialSettings`, `getBrowserSerialApi()`, and `getUsbSerialCapability()`.

- [ ] **Step 1: Write fake-stream tests for open, decode, and settings**

Create `frontend/tests/fakes/webSerial.ts` with this reusable native-stream fixture:

```ts
import { vi } from 'vitest';
import type {
  SerialApi,
  SerialPortLike,
  UsbSerialSettings,
} from '../../src/features/terminal/UsbSerialTransport';

export const defaultSerialSettings: UsbSerialSettings = {
  baudRate: 9600,
  dataBits: 8,
  stopBits: 1,
  parity: 'none',
  flowControl: 'none',
};

export interface SerialFixtureOptions {
  cancel?: () => void | Promise<void>;
  write?: (chunk: Uint8Array) => void | Promise<void>;
}

class FakeSerialPort extends EventTarget implements SerialPortLike {
  readonly open = vi.fn(async (_options: UsbSerialSettings) => undefined);
  readonly close = vi.fn(async () => undefined);

  constructor(
    readonly readable: ReadableStream<Uint8Array>,
    readonly writable: WritableStream<Uint8Array>,
  ) {
    super();
  }
}

export function serialFixture(options: SerialFixtureOptions = {}) {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const cancel = vi.fn(options.cancel ?? (() => undefined));
  const write = vi.fn(options.write ?? (() => undefined));
  const readable = new ReadableStream<Uint8Array>({
    start(value) { controller = value; },
    cancel,
  });
  const writable = new WritableStream<Uint8Array>({ write });
  const port = new FakeSerialPort(readable, writable);
  const removeEventListener = vi.spyOn(port, 'removeEventListener');
  const api: SerialApi = { requestPort: vi.fn(async () => port) };
  return {
    api,
    port,
    cancel,
    write,
    removeEventListener,
    enqueue: (value: Uint8Array) => controller.enqueue(value),
    failRead: () => controller.error(new Error('raw serial read detail')),
    disconnect: () => port.dispatchEvent(new Event('disconnect')),
  };
}

export const nextMicrotask = () => new Promise<void>((resolve) => queueMicrotask(resolve));
```

Create `frontend/tests/usb-serial-transport.test.ts`, import that fixture plus `TerminalTransportEvent`, and add these first tests:

```ts
it('opens 8N1 without flow control and decodes split multibyte output', async () => {
  const euro = new TextEncoder().encode('€');
  const { api, port, enqueue } = serialFixture();
  const events: TerminalTransportEvent[] = [];
  const transport = new UsbSerialTransport(api, {
    baudRate: 9600, dataBits: 8, stopBits: 1, parity: 'none', flowControl: 'none',
  });

  await transport.open((event) => events.push(event));
  enqueue(euro.slice(0, 1));
  enqueue(euro.slice(1));
  await nextMicrotask();

  expect(port.open).toHaveBeenCalledWith({
    baudRate: 9600, dataBits: 8, stopBits: 1, parity: 'none', flowControl: 'none',
  });
  expect(events.filter((event) => event.type === 'output')).toEqual([
    { type: 'output', data: '€' },
  ]);
});
```

Add a separate partial reads case which enqueues `show ` and `version\r\n` in different chunks and expects two ordered output events without concatenating or persisting them.

- [ ] **Step 2: Run the focused test to verify it fails**

Run from `frontend/`:

```text
npm test -- --run tests/usb-serial-transport.test.ts
```

Expected: FAIL because `UsbSerialTransport` does not exist.

- [ ] **Step 3: Define the narrow Web Serial types and capability check**

At the top of `frontend/src/features/terminal/UsbSerialTransport.ts`, define only the browser surface this project uses:

```ts
export interface UsbSerialSettings {
  baudRate: number;
  dataBits: 8;
  stopBits: 1;
  parity: 'none';
  flowControl: 'none';
}

export interface SerialPortLike extends EventTarget {
  readonly readable: ReadableStream<Uint8Array> | null;
  readonly writable: WritableStream<Uint8Array> | null;
  open(options: UsbSerialSettings): Promise<void>;
  close(): Promise<void>;
}

export interface SerialApi {
  requestPort(): Promise<SerialPortLike>;
}

interface SerialNavigator extends Navigator { serial?: SerialApi }
interface SerialPermissionsPolicy { allowsFeature(feature: string): boolean }
interface SerialDocument extends Document { permissionsPolicy?: SerialPermissionsPolicy }

export type UsbSerialCapability =
  | { available: true }
  | { available: false; code: 'browser_unsupported' | 'secure_context_required' | 'serial_policy_blocked' };

export function getBrowserSerialApi(): SerialApi | undefined {
  return (navigator as SerialNavigator).serial;
}

export function getUsbSerialCapability(): UsbSerialCapability {
  if (!window.isSecureContext) return { available: false, code: 'secure_context_required' };
  if (!(document as SerialDocument).permissionsPolicy?.allowsFeature('serial')) {
    if ((document as SerialDocument).permissionsPolicy !== undefined) {
      return { available: false, code: 'serial_policy_blocked' };
    }
  }
  return getBrowserSerialApi() === undefined
    ? { available: false, code: 'browser_unsupported' }
    : { available: true };
}
```

- [ ] **Step 4: Add incremental read ownership and sanitized errors**

Create `UsbSerialTransport implements TerminalTransport` with nullable private fields for port, reader, writer, decoder, listener, read loop, write tail, pending bytes, close promise, and closing/disposed flags. `open()` must call `requestPort()` before its first `await` returns control to React, attach the port disconnect listener, open with the supplied settings, acquire both stream locks, emit `connected`, and start this read loop:

```ts
private async read(): Promise<void> {
  try {
    while (!this.closing && this.reader !== null) {
      const { value, done } = await this.reader.read();
      if (done) break;
      if (value !== undefined && value.byteLength > 0) {
        const output = this.decoder?.decode(value, { stream: true }) ?? '';
        if (output) this.listener?.({ type: 'output', data: output });
      }
    }
    const finalOutput = this.decoder?.decode() ?? '';
    if (finalOutput) this.listener?.({ type: 'output', data: finalOutput });
  } catch {
    if (!this.closing) this.fail('serial_read_failed', 'Serial read failed');
  }
}
```

Map open exceptions only by `DOMException.name`: `NotFoundError` to cancelled/idle, `NotAllowedError` to `permission_denied`, `SecurityError` to `serial_access_blocked`, and every other open failure to `port_unavailable`. Do not retain the exception or its message as a property or `cause`.

- [ ] **Step 5: Add the bounded serialized write queue**

Encode before enqueue. Reject a chunk larger than 4,096 bytes or a chunk which would make pending bytes exceed 65,536. The rejected chunk must not reach `writer.write()`:

```ts
async write(data: string): Promise<void> {
  if (this.closing || this.writer === null) {
    throw new TerminalTransportError('serial_write_failed', 'Serial write failed');
  }
  const bytes = new TextEncoder().encode(data);
  if (
    bytes.byteLength > USB_WRITE_CHUNK_LIMIT_BYTES ||
    this.pendingWriteBytes + bytes.byteLength > USB_WRITE_QUEUE_LIMIT_BYTES
  ) {
    const error = new TerminalTransportError(
      'serial_write_queue_full',
      'Serial write queue full',
    );
    this.listener?.({ type: 'error', code: error.code, message: error.message });
    void this.close(Date.now() + TERMINAL_CLEANUP_TIMEOUT_MS);
    throw error;
  }
  this.pendingWriteBytes += bytes.byteLength;
  const writer = this.writer;
  const operation = this.writeTail.then(async () => {
    try {
      await writer.write(bytes);
    } catch {
      const error = new TerminalTransportError('serial_write_failed', 'Serial write failed');
      if (!this.closing) this.fail(error.code, error.message);
      throw error;
    }
  });
  this.writeTail = operation
    .catch(() => undefined)
    .finally(() => {
      this.pendingWriteBytes = Math.max(0, this.pendingWriteBytes - bytes.byteLength);
    });
  await operation;
}
```

Add a test which calls `transport.write('x'.repeat(4_096))` sixteen times in the same synchronous turn without awaiting, then calls it a seventeenth time and expects `serial_write_queue_full`. Await the accepted operations and assert the sink received exactly sixteen 4,096-byte chunks and no partial seventeenth write. Add an individual 4,097-byte rejection case.

- [ ] **Step 6: Add idempotent deadline-aware serial cleanup**

Use one `closePromise`. Serial cleanup only must: block writes; remove the disconnect listener; cancel and release the reader; settle the read loop; settle writes or abort the writer; release the writer; close the port; clear decoder, queue, and serial references. Race each awaited operation against the remaining `deadlineAt - Date.now()` and continue later release attempts in `finally` blocks. If any operation exhausts the deadline, reject only with `TerminalTransportError('cleanup_timed_out', 'Cleanup timed out')` after owned references are cleared.

Use this helper for each awaited cleanup operation and accumulate a `timedOut` boolean rather than throwing raw failures:

```ts
async function settleBefore(promise: Promise<unknown>, deadlineAt: number): Promise<boolean> {
  const remaining = Math.max(0, deadlineAt - Date.now());
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise.then(() => true, () => true),
      new Promise<boolean>((resolve) => {
        timeout = setTimeout(() => resolve(false), remaining);
      }),
    ]);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}
```

Always call `releaseLock()` and clear references in `finally`, even when `settleBefore()` returns `false`. After the last release attempt, throw only the sanitized cleanup-timeout error when `timedOut` is true.

Add these explicit tests:

```ts
it('releases both stream locks and closes once after user close', async () => {
  const fixture = serialFixture();
  const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
  await transport.open(vi.fn());
  await transport.close(Date.now() + 5_000);
  expect(fixture.port.readable.locked).toBe(false);
  expect(fixture.port.writable.locked).toBe(false);
  expect(fixture.port.close).toHaveBeenCalledOnce();
});

it('maps read failure without exposing the raw exception and closes', async () => {
  const fixture = serialFixture();
  const events: TerminalTransportEvent[] = [];
  const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
  await transport.open((event) => events.push(event));
  fixture.failRead();
  await nextMicrotask();
  expect(events).toContainEqual({
    type: 'error', code: 'serial_read_failed', message: 'Serial read failed',
  });
  expect(JSON.stringify(events)).not.toContain('raw serial read detail');
});

it('maps write failure without exposing the raw exception and closes', async () => {
  const fixture = serialFixture({
    write: async () => { throw new Error('raw serial write detail'); },
  });
  const events: TerminalTransportEvent[] = [];
  const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
  await transport.open((event) => events.push(event));
  await expect(transport.write('x')).rejects.toBeDefined();
  expect(events).toContainEqual({
    type: 'error', code: 'serial_write_failed', message: 'Serial write failed',
  });
  expect(JSON.stringify(events)).not.toContain('raw serial write detail');
});

it('times out a hung reader cancellation, clears references, and remains idempotent', async () => {
  vi.useFakeTimers();
  const fixture = serialFixture({ cancel: () => new Promise<void>(() => undefined) });
  const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
  await transport.open(vi.fn());
  const first = transport.close(Date.now() + 5_000);
  const second = transport.close(Date.now() + 5_000);
  await vi.advanceTimersByTimeAsync(5_000);
  await expect(first).rejects.toMatchObject({ code: 'cleanup_timed_out' });
  await expect(second).rejects.toMatchObject({ code: 'cleanup_timed_out' });
  expect(fixture.removeEventListener).toHaveBeenCalled();
  vi.useRealTimers();
});
```

Simulate unexpected adapter removal by dispatching `disconnect` while `reader.read()` and `writer.write()` are unresolved; assert a sanitized `device_disconnected` event, write blocking, lock release attempts, port cleanup, and no reconnect.

- [ ] **Step 7: Verify the serial transport**

Run from `frontend/`:

```text
npm test -- --run tests/usb-serial-transport.test.ts tests/terminal-input-policy.test.ts
npm run typecheck
npm run lint
```

Expected: all cases pass without a real serial API or device.

- [ ] **Step 8: Commit the USB transport**

```text
git add frontend/src/features/terminal/UsbSerialTransport.ts frontend/tests/fakes/webSerial.ts frontend/tests/usb-serial-transport.test.ts
node .gitnexus/run.cjs detect-changes --scope staged
git diff --cached --check
git commit -m "feat: add bounded USB serial transport"
```

Expected GitNexus scope: new frontend serial symbols and test references only; no API route, backend symbol, or network-driver process.

---

### Task 3: Shared Session and Separate SSH Transport

**Files:**
- Create: `frontend/src/features/terminal/SshWebSocketTransport.ts`
- Create: `frontend/src/features/terminal/TerminalSession.tsx`
- Modify: `frontend/src/features/inventory/TerminalPanel.tsx:1-177`
- Modify: `frontend/tests/terminal-panel.test.tsx:1-85`

**Interfaces:**
- Consumes: Task 1's `TerminalTransport` and input policy; Task 2's deadline behavior.
- Produces: `SshWebSocketTransport` and reusable `TerminalSession` with `createTransport`, risk copy, optional authorization acknowledgement, input policy, configuration slot, and reset callback.

- [ ] **Step 1: Re-run mandatory impact analysis and report it**

```text
node .gitnexus/run.cjs impact TerminalSession --direction upstream --file frontend/src/features/inventory/TerminalPanel.tsx --kind Function
node .gitnexus/run.cjs impact TerminalPanel --direction upstream --file frontend/src/features/inventory/TerminalPanel.tsx --kind Function
node .gitnexus/run.cjs impact websocketUrl --direction upstream --file frontend/src/features/inventory/TerminalPanel.tsx --kind Function
```

Expected from the current index: LOW risk; `TerminalSession` has one direct caller (`TerminalPanel`), and `websocketUrl` reaches only those two terminal functions. Stop and warn if the refreshed index reports HIGH or CRITICAL.

- [ ] **Step 2: Extend the existing tests before refactoring**

Update the xterm mock so each constructed terminal records its `onData` callback, writes, and `dispose()` call. Add FitAddon `dispose()` tracking. Add tests which assert:

```ts
const terminalMocks = vi.hoisted(() => ({
  instances: [] as Array<{
    emitInput: (data: string) => void;
    write: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    cols = 80;
    rows = 24;
    private input: (data: string) => void = () => undefined;
    readonly write = vi.fn();
    readonly dispose = vi.fn();
    constructor() {
      terminalMocks.instances.push({
        emitInput: (data: string) => this.input(data),
        write: this.write,
        dispose: this.dispose,
      });
    }
    loadAddon() { return undefined; }
    open() { return undefined; }
    onData(input: (data: string) => void) {
      this.input = input;
      return { dispose: vi.fn() };
    }
  },
}));

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit = vi.fn();
    dispose = vi.fn();
  },
}));

class FakeTransport implements TerminalTransport {
  readonly kind = 'usb' as const;
  listener: TerminalTransportListener | undefined;
  readonly open = vi.fn(async (listener: TerminalTransportListener) => {
    this.listener = listener;
    listener({ type: 'status', status: 'connected' });
  });
  readonly write = vi.fn(async (_data: string) => undefined);
  readonly resize = vi.fn((_columns: number, _rows: number) => undefined);
  readonly close = vi.fn(async (_deadlineAt: number) => undefined);
  emit(event: TerminalTransportEvent) { this.listener?.(event); }
}

it('keeps SSH raw and sends the existing Direct Mode acknowledgement', async () => {
  const user = userEvent.setup();
  render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
  await user.click(screen.getByRole('button', { name: 'I understand — open Direct Mode' }));
  const socket = FakeWebSocket.instances[0];
  if (socket === undefined) throw new Error('Expected an SSH WebSocket.');
  socket.readyState = FakeWebSocket.OPEN;
  socket.onopen?.();
  terminalMocks.instances[0]?.emitInput('\r');
  expect(socket.sent).toEqual([
    JSON.stringify({ type: 'accept_direct_mode' }),
    JSON.stringify({ type: 'input', data: '\r' }),
  ]);
});

it('clears a pending multiline confirmation on close', async () => {
  const transport = new FakeTransport();
  const { unmount } = renderUsbLikeSession(transport);
  await userEvent.click(screen.getByRole('button', { name: 'Open test session' }));
  terminalMocks.instances[0]?.emitInput('show version\r\nreload');
  expect(screen.getByRole('button', { name: 'Send 2 lines' })).toBeVisible();
  unmount();
  expect(transport.write).not.toHaveBeenCalled();
  expect(transport.close).toHaveBeenCalledOnce();
});

it('constructs fresh transport and xterm objects after a normal close', async () => {
  const transports: FakeTransport[] = [];
  renderUsbLikeSession(() => {
    const transport = new FakeTransport();
    transports.push(transport);
    return transport;
  });
  await userEvent.click(screen.getByRole('button', { name: 'Open test session' }));
  transports[0]?.emit({ type: 'status', status: 'closed' });
  await userEvent.click(await screen.findByRole('button', { name: 'Open test session' }));
  expect(transports).toHaveLength(2);
  expect(terminalMocks.instances).toHaveLength(2);
  expect(transports[1]).not.toBe(transports[0]);
});

it('disposes UI resources after the five-second cleanup deadline', async () => {
  vi.useFakeTimers();
  const transport = new FakeTransport();
  transport.close.mockImplementation(() => new Promise<void>(() => undefined));
  renderUsbLikeSession(transport);
  await userEvent.click(screen.getByRole('button', { name: 'Open test session' }));
  await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
  await vi.advanceTimersByTimeAsync(5_000);
  expect(terminalMocks.instances[0]?.dispose).toHaveBeenCalledOnce();
  expect(screen.getByText('Cleanup timed out')).toBeVisible();
  vi.useRealTimers();
});
```

Define the test renderer directly below `FakeTransport`:

```tsx
const renderUsbLikeSession = (
  value: FakeTransport | (() => FakeTransport),
) => render(
  <TerminalSession
    createTransport={typeof value === 'function' ? value : () => value}
    warningTitle="Test Direct Mode"
    warningBody="Test warning"
    acknowledgementLabel="Open test session"
    inputPolicy={{ lineEnding: 'cr', localEcho: false, confirmMultiline: true }}
    ariaLabel="Test terminal"
    note="Test session"
  />,
);
```

- [ ] **Step 3: Run the terminal regression test and observe the intended failures**

Run from `frontend/`:

```text
npm test -- --run tests/terminal-panel.test.tsx
```

Expected: existing tests pass, while new shared-session/fresh-cleanup cases fail because the new modules do not exist.

- [ ] **Step 4: Move only WebSocket ownership into `SshWebSocketTransport`**

Create `frontend/src/features/terminal/SshWebSocketTransport.ts`. Move `websocketUrl`, WebSocket construction, JSON parsing, Direct Mode acknowledgement, server status/output/error forwarding, resize messages, and socket close into the class. Keep the current URL and protocol exactly:

```ts
export class SshWebSocketTransport implements TerminalTransport {
  readonly kind = 'ssh' as const;
  private socket: WebSocket | null = null;
  private closePromise: Promise<void> | null = null;

  constructor(private readonly deviceId: string) {}

  async open(listener: TerminalTransportListener): Promise<void> {
    listener({ type: 'status', status: 'connecting' });
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.socket = new WebSocket(
      `${protocol}//${window.location.host}/ws/terminal/${encodeURIComponent(this.deviceId)}`,
    );
    this.socket.onopen = () => {
      this.socket?.send(JSON.stringify({ type: 'accept_direct_mode' }));
    };
    this.socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as Record<string, unknown>;
        if (message.type === 'output' && typeof message.data === 'string') {
          listener({ type: 'output', data: message.data });
        } else if (
          message.type === 'status' &&
          (message.status === 'connecting' || message.status === 'connected' || message.status === 'closed')
        ) {
          listener({ type: 'status', status: message.status });
        } else if (
          message.type === 'error' &&
          typeof message.code === 'string' &&
          typeof message.message === 'string'
        ) {
          listener({ type: 'error', code: message.code, message: message.message });
        } else {
          listener({
            type: 'error', code: 'invalid_terminal_message',
            message: 'The terminal server returned an invalid message.',
          });
        }
      } catch {
        listener({
          type: 'error', code: 'invalid_terminal_message',
          message: 'The terminal server returned an invalid message.',
        });
      }
    };
    this.socket.onerror = () => listener({
      type: 'error', code: 'terminal_service_unavailable',
      message: 'Unable to reach the terminal service.',
    });
    this.socket.onclose = () => listener({ type: 'status', status: 'closed' });
  }

  async write(data: string): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'input', data }));
    }
  }

  resize(columns: number, rows: number): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'resize', columns, rows }));
    }
  }

  close(_deadlineAt: number): Promise<void> {
    this.closePromise ??= Promise.resolve().then(() => {
      this.socket?.close();
      this.socket = null;
    });
    return this.closePromise;
  }
}
```

- [ ] **Step 5: Create the ownership-correct shared session**

Create `frontend/src/features/terminal/TerminalSession.tsx` with this prop contract:

```ts
interface TerminalSessionProps {
  createTransport: () => TerminalTransport;
  warningTitle: string;
  warningBody: string;
  acknowledgementLabel: string;
  requireAuthorization?: boolean;
  inputPolicy: TerminalInputPolicy;
  ariaLabel: string;
  note: string;
  openDisabled?: boolean;
  configuration?: ReactNode;
  onReset?: () => void;
}
```

The open button handler—not an effect—must synchronously create a new transport and call `transport.open(listener)` so `requestPort()` retains browser user activation. Create a new xterm/FitAddon, input subscription, ResizeObserver, resize listener, and `pagehide` listener for that same session.

Handle xterm input with `prepareTerminalInput()`. Raw SSH input writes immediately. USB multiline input populates `{ data, lineCount }` in memory and renders **Send N lines** and **Cancel** without displaying content. Local echo writes only the exact data accepted for transmission. Clear the pending buffer after send, cancel, write failure, disconnect, route/unmount, or shutdown.

Implement top-level shutdown in this order:

```ts
const shutdown = async (error?: { code: string; message: string }, disposed = false) => {
  if (shutdownPromise.current !== null) return shutdownPromise.current;
  shutdownPromise.current = (async () => {
    setAcceptingInput(false);
    setPendingPaste(undefined);
    const deadlineAt = Date.now() + TERMINAL_CLEANUP_TIMEOUT_MS;
    try {
      await withCleanupTimeout(
        transportRef.current?.close(deadlineAt) ?? Promise.resolve(),
        TERMINAL_CLEANUP_TIMEOUT_MS,
      );
    } catch {
      error ??= { code: 'cleanup_timed_out', message: 'Cleanup timed out' };
    } finally {
      inputSubscription.current?.dispose();
      resizeObserver.current?.disconnect();
      window.removeEventListener('resize', resizeHandler.current);
      window.removeEventListener('pagehide', pageHideHandler.current);
      fitAddon.current?.dispose();
      terminal.current?.dispose();
      clearAllSessionRefs();
      if (!disposed) {
        setStatus('idle');
        setError(error);
        setAccepted(false);
        setAuthorized(false);
        onReset?.();
      }
    }
  })();
  return shutdownPromise.current;
};
```

The unmount effect invokes `void shutdown(undefined, true)`. Late transport events check a per-session disposed token. A later open resets the shutdown promise and constructs entirely new objects.

Define the timeout helper in the same module:

```ts
async function withCleanupTimeout(cleanup: Promise<void>, milliseconds: number): Promise<void> {
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      cleanup,
      new Promise<void>((_resolve, reject) => {
        timeout = setTimeout(
          () => reject(new TerminalTransportError('cleanup_timed_out', 'Cleanup timed out')),
          milliseconds,
        );
      }),
    ]);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}
```

Define `clearAllSessionRefs()` to null the transport, terminal, FitAddon, input subscription, observer, resize handler, and pagehide handler refs after their owners have been disposed.

- [ ] **Step 6: Reduce `TerminalPanel` to SSH tab composition**

Keep `MAX_TERMINALS = 3`, tab creation/removal, and existing copy. Replace the old internal `TerminalSession` with the shared component:

```tsx
<TerminalSession
  createTransport={() => new SshWebSocketTransport(deviceId)}
  warningTitle="Direct Mode — no rollback protection"
  warningBody="Commands run on the device exactly as typed and may change its configuration. The app does not parse, approve, record, or automatically undo terminal commands."
  acknowledgementLabel="I understand — open Direct Mode"
  inputPolicy={{ lineEnding: 'raw', localEcho: false, confirmMultiline: false }}
  ariaLabel="Device terminal"
  note="Idle sessions close after 15 minutes. Output is capped and never saved by the app."
/>
```

- [ ] **Step 7: Verify shared cleanup and unchanged SSH behavior**

Run from `frontend/`:

```text
npm test -- --run tests/terminal-panel.test.tsx
npm run typecheck
npm run lint
```

Expected: acknowledgement JSON, raw input, resize, three-tab cap, error mapping, pending-buffer clearing, cleanup timeout, and fresh-object tests all pass.

- [ ] **Step 8: Commit the shared seam**

```text
git add frontend/src/features/terminal/SshWebSocketTransport.ts frontend/src/features/terminal/TerminalSession.tsx frontend/src/features/inventory/TerminalPanel.tsx frontend/tests/terminal-panel.test.tsx
node .gitnexus/run.cjs detect-changes --scope staged
git diff --cached --check
git commit -m "refactor: separate terminal transports"
```

Expected GitNexus scope: the existing frontend terminal symbols and new shared/SSH modules only. No backend terminal handler change is expected.

---

### Task 4: Standalone Manual USB Console UI

**Files:**
- Create: `frontend/src/features/inventory/UsbConsoleDialog.tsx`
- Modify: `frontend/src/features/inventory/InventoryPage.tsx:1-387`
- Modify: `frontend/src/components/AppShell.tsx:1-161`
- Modify: `frontend/src/features/access/AccessGate.tsx`
- Modify: `frontend/src/features/inventory/DeviceInspector.tsx:640-670`
- Modify: `frontend/src/styles.css:1851-1935`
- Create: `frontend/tests/usb-console-dialog.test.tsx`

**Interfaces:**
- Consumes: `UsbSerialTransport`, `getUsbSerialCapability()`, `getBrowserSerialApi()`, `parseBaudRate()`, and `TerminalSession`.
- Produces: `UsbConsoleDialog` and an Inventory-level entry point available with zero registered devices.

- [ ] **Step 1: Re-run impact analysis for every existing component symbol**

```text
node .gitnexus/run.cjs impact InventoryPage --direction upstream --file frontend/src/features/inventory/InventoryPage.tsx --kind Function
node .gitnexus/run.cjs impact AppShell --direction upstream --file frontend/src/components/AppShell.tsx --kind Function
node .gitnexus/run.cjs impact AccessGate --direction upstream --file frontend/src/features/access/AccessGate.tsx --kind Function
node .gitnexus/run.cjs impact DeviceInspector --direction upstream --file frontend/src/features/inventory/DeviceInspector.tsx --kind Function
```

Expected from the current index: all LOW risk; `InventoryPage` reaches `AppShell` then `App`, `AppShell` reaches `App`, and `DeviceInspector` has one direct consumer chain. Stop and warn if any result becomes HIGH or CRITICAL.

- [ ] **Step 2: Write capability, settings, authorization, and privacy tests**

Create `frontend/tests/usb-console-dialog.test.tsx` with an xterm mock and injected fake `navigator.serial`. Cover:

```ts
const renderDialog = (
  fixture = serialFixture(),
  capability: UsbSerialCapability = { available: true },
) => {
  render(<UsbConsoleDialog serialApi={fixture.api} capability={capability} />);
  return fixture;
};

it('requires authorization acknowledgement before requesting a port', async () => {
  const fixture = serialFixture();
  render(<UsbConsoleDialog serialApi={fixture.api} capability={{ available: true }} />);
  expect(screen.getByText(/can modify, restart, or erase/)).toBeVisible();
  expect(screen.getByRole('button', { name: 'Open USB Direct Mode' })).toBeDisabled();
  await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
  await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
  expect(fixture.api.requestPort).toHaveBeenCalledOnce();
});

it('passes presets and validated custom baud with selected input policy', async () => {
  const fixture = renderDialog();
  await userEvent.selectOptions(screen.getByLabelText('Baud rate'), 'custom');
  await userEvent.clear(screen.getByLabelText('Custom baud rate'));
  await userEvent.type(screen.getByLabelText('Custom baud rate'), '0');
  expect(screen.getByRole('button', { name: 'Open USB Direct Mode' })).toBeDisabled();
  await userEvent.clear(screen.getByLabelText('Custom baud rate'));
  await userEvent.type(screen.getByLabelText('Custom baud rate'), '250000');
  await userEvent.selectOptions(screen.getByLabelText('Line ending'), 'crlf');
  await userEvent.click(screen.getByRole('checkbox', { name: 'Local echo' }));
  await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
  await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
  expect(fixture.port.open).toHaveBeenCalledWith({
    baudRate: 250000, dataBits: 8, stopBits: 1, parity: 'none', flowControl: 'none',
  });
});

it.each([
  ['browser_unsupported' as const, 'Chrome or Edge is required'],
  ['secure_context_required' as const, 'A secure context is required'],
  ['serial_policy_blocked' as const, 'Serial access is blocked by policy'],
])('renders sanitized capability state %s without requesting a port', (code, message) => {
  const fixture = renderDialog(serialFixture(), { available: false, code });
  expect(screen.getByText(message)).toBeVisible();
  expect(fixture.api.requestPort).not.toHaveBeenCalled();
});

it('creates no REST, WebSocket, storage, IndexedDB, analytics, or reporting traffic', async () => {
  const fetchSpy = vi.fn();
  const socketSpy = vi.fn();
  vi.stubGlobal('fetch', fetchSpy);
  vi.stubGlobal('WebSocket', socketSpy);
  const localSet = vi.spyOn(Storage.prototype, 'setItem');
  const indexedOpen = vi.fn();
  vi.stubGlobal('indexedDB', { open: indexedOpen });
  const sendBeacon = vi.fn();
  Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: sendBeacon });
  const fixture = renderDialog();
  await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
  await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
  fixture.enqueue(new TextEncoder().encode('ready'));
  await nextMicrotask();
  await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }));

  const denied = serialFixture();
  vi.mocked(denied.api.requestPort).mockRejectedValueOnce(
    new DOMException('raw browser detail', 'NotAllowedError'),
  );
  cleanup();
  renderDialog(denied);
  await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
  await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
  expect(screen.getByText('Permission denied')).toBeVisible();
  expect(screen.queryByText('raw browser detail')).not.toBeInTheDocument();
  expect(fetchSpy).not.toHaveBeenCalled();
  expect(socketSpy).not.toHaveBeenCalled();
  expect(localSet).not.toHaveBeenCalled();
  expect(indexedOpen).not.toHaveBeenCalled();
  expect(sendBeacon).not.toHaveBeenCalled();
});
```

Add a test which closes and reopens, then asserts the authorization checkbox is clear, settings are reset to 9600/CR/local-echo-off, and distinct transport/xterm instances are used. Add an InventoryPage test with mocked `api.devices()` returning `[]` which asserts **Open USB Console** is visible before **Add first device**.

- [ ] **Step 3: Run the UI test to verify it fails**

Run from `frontend/`:

```text
npm test -- --run tests/usb-console-dialog.test.tsx
```

Expected: FAIL because `UsbConsoleDialog` and the Inventory entry do not exist.

- [ ] **Step 4: Build the minimal USB console composition**

Create `UsbConsoleDialog.tsx` with presets `[9600, 19200, 38400, 57600, 115200]`, a `Custom` option, fixed 8N1/no-flow copy, line-ending select, local-echo checkbox, and capability-specific `AppState`. Keep defaults in a constant and reset them in `TerminalSession.onReset`.

Use this testable boundary and in-memory settings shape:

```ts
interface UsbConsoleDialogProps {
  serialApi?: SerialApi;
  capability?: UsbSerialCapability;
}

interface UsbConsoleSettings {
  baudSelection: '9600' | '19200' | '38400' | '57600' | '115200' | 'custom';
  customBaud: string;
  lineEnding: 'cr' | 'lf' | 'crlf';
  localEcho: boolean;
}

const DEFAULT_USB_SETTINGS: UsbConsoleSettings = {
  baudSelection: '9600',
  customBaud: '',
  lineEnding: 'cr',
  localEcho: false,
};
```

Resolve `serialApi ?? getBrowserSerialApi()` and `capability ?? getUsbSerialCapability()` at render time without storing either. Resolve the active baud with `parseBaudRate(settings.baudSelection === 'custom' ? settings.customBaud : settings.baudSelection)` and keep the open action disabled while it is `null`.

Build `settingsForm` from existing field components:

```tsx
const baudRate = parseBaudRate(
  settings.baudSelection === 'custom' ? settings.customBaud : settings.baudSelection,
);
const settingsForm = (
  <div className="usb-console-settings">
    <SelectField
      label="Baud rate"
      value={settings.baudSelection}
      onChange={(event) => setSettings((current) => ({
        ...current,
        baudSelection: event.target.value as UsbConsoleSettings['baudSelection'],
      }))}
    >
      {[9600, 19200, 38400, 57600, 115200].map((value) => (
        <option key={value} value={String(value)}>{value}</option>
      ))}
      <option value="custom">Custom</option>
    </SelectField>
    {settings.baudSelection === 'custom' ? (
      <InputField
        label="Custom baud rate"
        type="number"
        min={1}
        max={0xffff_ffff}
        value={settings.customBaud}
        onChange={(event) => setSettings((current) => ({
          ...current, customBaud: event.target.value,
        }))}
        error={baudRate === null ? 'Enter a whole baud rate from 1 to 4294967295.' : undefined}
      />
    ) : null}
    <SelectField
      label="Line ending"
      value={settings.lineEnding}
      onChange={(event) => setSettings((current) => ({
        ...current, lineEnding: event.target.value as UsbConsoleSettings['lineEnding'],
      }))}
    >
      <option value="cr">CR</option>
      <option value="lf">LF</option>
      <option value="crlf">CRLF</option>
    </SelectField>
    <label className="usb-console-echo">
      <input
        type="checkbox"
        checked={settings.localEcho}
        onChange={(event) => setSettings((current) => ({
          ...current, localEcho: event.target.checked,
        }))}
      />
      Local echo
    </label>
    <p>8 data bits · 1 stop bit · no parity · no flow control</p>
  </div>
);
```

When available, compose:

```tsx
<TerminalSession
  createTransport={() => {
    if (serialApi === undefined || baudRate === null) {
      throw new TerminalTransportError('invalid_serial_settings', 'Serial settings are invalid');
    }
    return new UsbSerialTransport(serialApi, {
      baudRate,
      dataBits: 8,
      stopBits: 1,
      parity: 'none',
      flowControl: 'none',
    });
  }}
  warningTitle="USB Direct Mode — commands can change hardware"
  warningBody="Commands are sent exactly as entered and can modify, restart, or erase the attached device. There is no preview, rollback, recording, or automatic recovery."
  acknowledgementLabel="I am authorized to access this attached device and understand the risk"
  requireAuthorization
  inputPolicy={{ lineEnding, localEcho, confirmMultiline: true }}
  ariaLabel="Manual USB console"
  note="Serial content stays in this browser tab and is destroyed when the session closes."
  openDisabled={baudRate === null || serialApi === undefined}
  configuration={settingsForm}
  onReset={() => setSettings(DEFAULT_USB_SETTINGS)}
/>
```

Do not catch and render `error.message`; capability and transport error codes map to fixed copy.

- [ ] **Step 5: Expose the modal before registration and correct safety copy**

In `InventoryPage`, add `usbConsoleOpen`, an **Open USB Console** button in `page-header__actions`, and a large Modal containing `UsbConsoleDialog`. This button is outside inventory empty/loading branches.

Change misleading global copy without weakening structured safety:

- Inventory heading: structured connections remain read-only; manual terminals are Direct Mode.
- Inventory metric: `Structured writes` / `Blocked` / `Manual terminals bypass automation`.
- AppShell safety card: `Structured automation is read-only`; mention Direct Mode separately.
- AppShell status bar: `Structured writes blocked`.
- AccessGate: `Structured safety foundation` rather than a blanket read-only claim.
- DeviceInspector footer: `Structured writes blocked · Terminal is Direct Mode`.

- [ ] **Step 6: Add focused styles using existing tokens**

Append only selectors needed for `.usb-console-settings`, `.usb-console-authorization`, `.terminal-multiline-warning`, and `.terminal-session__actions`. Reuse `.field`, `.input`, `.inline-notice`, `.button`, `.terminal-session`, and responsive grid rules; do not introduce a component library or animation.

- [ ] **Step 7: Verify UI safety and privacy behavior**

Run from `frontend/`:

```text
npm test -- --run tests/usb-console-dialog.test.tsx tests/terminal-panel.test.tsx tests/access-gate.test.tsx tests/device-inspector.test.tsx
npm run typecheck
npm run lint
```

Expected: all tests pass; USB success and error paths produce zero backend/storage calls, and existing SSH/device tests remain green.

- [ ] **Step 8: Commit the Manual USB Console UI**

```text
git add frontend/src/features/inventory/UsbConsoleDialog.tsx frontend/src/features/inventory/InventoryPage.tsx frontend/src/components/AppShell.tsx frontend/src/features/access/AccessGate.tsx frontend/src/features/inventory/DeviceInspector.tsx frontend/src/styles.css frontend/tests/usb-console-dialog.test.tsx
node .gitnexus/run.cjs detect-changes --scope staged
git diff --cached --check
git commit -m "feat: add manual USB console"
```

Expected GitNexus scope: Inventory/AppShell/DeviceInspector presentation and new terminal UI only; no API, job, repository, model, or driver flow.

---

### Task 5: Production and Development Permissions Policy

**Files:**
- Modify: `frontend/nginx.conf:11-20,47-49`
- Modify: `frontend/vite.config.ts:6-17`
- Create: `frontend/tests/serving-policy.test.ts`

**Interfaces:**
- Consumes: Existing Nginx security headers and Vite development server configuration.
- Produces: `Permissions-Policy` allowing only same-origin serial access on the application document in both serving paths.

- [ ] **Step 1: Write the failing serving-policy regression**

Create `frontend/tests/serving-policy.test.ts`:

```ts
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

describe('serial permissions policy', () => {
  it('allows same-origin serial on the production document response', () => {
    const nginx = read('../nginx.conf');
    expect(nginx).toContain('serial=(self)');
    expect(nginx.match(/serial=\(self\)/g)).toHaveLength(2);
  });

  it('sets the same policy on the Vite development server', () => {
    expect(read('../vite.config.ts')).toContain(
      "'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), serial=(self)'",
    );
  });
});
```

The two Nginx occurrences are deliberate: the server-level header and the exact `/index.html` location, whose `Cache-Control` header otherwise prevents inheritance.

- [ ] **Step 2: Run the focused test to verify it fails**

Run from `frontend/`:

```text
npm test -- --run tests/serving-policy.test.ts
```

Expected: FAIL because neither serving configuration currently includes `serial=(self)`.

- [ ] **Step 3: Add the production and development headers**

In `nginx.conf`, change the server-level policy to:

```nginx
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), serial=(self)" always;
```

Repeat that exact `add_header` inside `location = /index.html` beside `Cache-Control` so the document response retains it.

In `vite.config.ts`, add:

```ts
server: {
  port: 5173,
  strictPort: true,
  headers: {
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), serial=(self)',
  },
},
```

- [ ] **Step 4: Run header, types, lint, and build checks**

Run from `frontend/`:

```text
npm test -- --run tests/serving-policy.test.ts
npm run typecheck
npm run lint
npm run build
```

Expected: all pass; no dependency or bundle warning is introduced.

- [ ] **Step 5: Commit serving policy**

```text
git add frontend/nginx.conf frontend/vite.config.ts frontend/tests/serving-policy.test.ts
node .gitnexus/run.cjs detect-changes --scope staged
git diff --cached --check
git commit -m "security: allow same-origin Web Serial"
```

Expected GitNexus scope: frontend serving configuration and its test only.

---

### Task 6: Documentation, Full Verification, and Hardware-Pending Status

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/safety-model.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/lab-test-guide.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`

**Interfaces:**
- Consumes: Passing Tasks 1-5 and frozen spec `docs/superpowers/specs/2026-07-20-usb-direct-mode-hardware-readiness-design.md`.
- Produces: Conservative automated-verification evidence, metadata-only hardware-validation procedure, and no claim of hardware support.

- [ ] **Step 1: Update architecture and safety documentation**

Document the direct browser path:

```text
Chrome/Edge on the local host
  -> Web Serial permission chooser
  -> operator-selected USB-to-console adapter
  -> attached device console
```

State that it bypasses the backend and structured driver safety pipeline; can modify, restart, or erase hardware; persists nothing; has bounded writes and five-second cleanup; creates fresh sessions; requires same-origin serial policy; and never auto-reconnects or sends generated commands.

- [ ] **Step 2: Update operator and lab guidance**

In `user-guide.md`, give the exact flow: open Inventory, select **Open USB Console**, select settings, acknowledge authorization/risk, choose the adapter, confirm multiline paste, disconnect, then register/test SSH separately when the operator has prepared the device outside Terraformer's automation.

In `lab-test-guide.md`, require explicit authorization before any hardware session and define the only permitted validation record fields:

```text
date | approver | browser/version | adapter type | device category |
application commit | non-command validation-step descriptions | pass/fail
```

Explicitly prohibit terminal output, commands, credentials, configuration, addresses, hostnames, serial numbers, adapter identifiers, and any serial-session content from the record.

- [ ] **Step 3: Update status without promoting support**

In `IMPLEMENTATION_STATUS.md`, add a Phase 2 Manual USB Console row with separate labels:

```text
Automated verification passed; hardware validation pending
```

In `CAPABILITY_MATRIX.md`, add a **Direct access paths** section rather than a structured read/write row. Mark USB Direct Mode `Implemented, lab unverified`, state that it is vendor-neutral manual access and can write, and leave the hardware evidence table empty until an authorized result exists.

- [ ] **Step 4: Run the complete frontend verification**

From `frontend/`:

```text
npm run verify
npm audit
```

Expected: TypeScript, ESLint, all Vitest tests, and production build pass; audit reports zero known vulnerabilities. Tests use fake streams only.

- [ ] **Step 5: Run the complete backend verification without device opt-ins**

From `backend/`:

```text
python -m ruff check --no-cache .
pyright
python -m pytest
```

Expected: lint/types pass and all routine tests pass; real-lab tests remain skipped because no lab opt-in is supplied.

- [ ] **Step 6: Validate Compose, migrations, images, and local health**

From the repository root:

```text
python deploy/init-secrets.py
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.yml -f deploy/compose.dev.yml config --quiet
docker compose -f deploy/compose.yml up --build --detach --wait
docker compose -f deploy/compose.yml exec api alembic current
docker compose -f deploy/compose.yml exec api alembic heads
docker compose -f deploy/compose.yml exec api alembic check
```

Expected: the non-rotating initializer retains valid existing secrets; both Compose configurations validate; all services become healthy; migrations remain at the existing head with no model drift. No device endpoint is contacted.

- [ ] **Step 7: Verify production and development headers at runtime**

Production PowerShell check:

```powershell
$response = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/' -Method Head
$response.Headers['Permissions-Policy']
```

Expected output contains `serial=(self)`.

Development PowerShell check from the repository root; the process must be hidden and always stopped:

```powershell
$vite = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--host','127.0.0.1' -WorkingDirectory '.\frontend' -WindowStyle Hidden -PassThru
try {
  $response = $null
  foreach ($attempt in 1..30) {
    try {
      $response = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -Method Head
      break
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  if ($response -eq $null) { throw 'Vite development server did not become ready.' }
  $response.Headers['Permissions-Policy']
} finally {
  Stop-Process -Id $vite.Id -ErrorAction SilentlyContinue
}
```

Expected output contains `serial=(self)`. This check contacts only the local frontend.

- [ ] **Step 8: Record exact automated evidence and run final change analysis**

Add the actual command results and date to `IMPLEMENTATION_STATUS.md`; do not predict counts before running. Keep the text **hardware validation pending**.

Then run:

```text
node .gitnexus/run.cjs detect-changes --scope compare --base-ref main
git diff --check
git status --short
```

Expected: only terminal UI/transports, frontend serving policy, tests, and the six status/operator documents are in scope. Investigate any backend model/driver/API flow or unrelated file before proceeding.

- [ ] **Step 9: Commit documentation and verified status**

```text
git add docs/architecture.md docs/safety-model.md docs/user-guide.md docs/lab-test-guide.md docs/IMPLEMENTATION_STATUS.md docs/CAPABILITY_MATRIX.md
node .gitnexus/run.cjs detect-changes --scope staged
git diff --cached --check
git commit -m "docs: record USB Direct Mode readiness"
```

Expected: the commit contains documentation only and retains lab-unverified status.

- [ ] **Step 10: Perform final verification-before-completion review**

Re-run `git status --short`, verify unrelated pre-existing changes are preserved, and compare every acceptance criterion in the frozen spec to fresh command output. Do not claim complete, fixed, supported, or hardware-ready beyond automated readiness unless those fresh checks pass. Do not perform the hardware validation.
