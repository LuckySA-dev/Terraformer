import { afterEach, describe, expect, it, vi } from 'vitest';
import { UsbSerialTransport } from '../src/features/terminal/UsbSerialTransport';
import type { TerminalTransportEvent } from '../src/features/terminal/transport';
import { defaultSerialSettings, nextMicrotask, serialFixture } from './fakes/webSerial';

afterEach(() => vi.useRealTimers());

describe('UsbSerialTransport', () => {
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

  it('emits partial reads in order', async () => {
    const { api, enqueue } = serialFixture();
    const events: TerminalTransportEvent[] = [];
    const transport = new UsbSerialTransport(api, {
      baudRate: 9600, dataBits: 8, stopBits: 1, parity: 'none', flowControl: 'none',
    });

    await transport.open((event) => events.push(event));
    enqueue(new TextEncoder().encode('show '));
    enqueue(new TextEncoder().encode('version\r\n'));
    await nextMicrotask();

    expect(events.filter((event) => event.type === 'output')).toEqual([
      { type: 'output', data: 'show ' },
      { type: 'output', data: 'version\r\n' },
    ]);
  });

  it('rejects a concurrent open without requesting a second port or replacing the listener', async () => {
    const fixture = serialFixture();
    let resolvePort!: (port: typeof fixture.port) => void;
    const pendingPort = new Promise<typeof fixture.port>((resolve) => { resolvePort = resolve; });
    fixture.requestPort.mockImplementation(() => pendingPort);
    const firstListener = vi.fn();
    const secondListener = vi.fn();
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);

    const first = transport.open(firstListener);
    const second = transport.open(secondListener);

    await expect(second).rejects.toMatchObject({ code: 'port_unavailable' });
    expect(fixture.requestPort).toHaveBeenCalledOnce();
    resolvePort(fixture.port);
    await first;

    expect(firstListener).toHaveBeenCalledWith({ type: 'status', status: 'connected' });
    expect(secondListener).not.toHaveBeenCalled();
  });

  it('closes a port that arrives after close during permission request without connecting', async () => {
    const fixture = serialFixture();
    let resolvePort!: (port: typeof fixture.port) => void;
    const pendingPort = new Promise<typeof fixture.port>((resolve) => { resolvePort = resolve; });
    fixture.requestPort.mockImplementation(() => pendingPort);
    const events: TerminalTransportEvent[] = [];
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);

    const opening = transport.open((event) => events.push(event));
    await transport.close(Date.now() + 5_000);
    resolvePort(fixture.port);

    await expect(opening).rejects.toMatchObject({ code: 'port_unavailable' });
    expect(fixture.port.open).not.toHaveBeenCalled();
    expect(fixture.port.close).toHaveBeenCalledOnce();
    expect(fixture.port.readable.locked).toBe(false);
    expect(fixture.port.writable.locked).toBe(false);
    expect(events).toEqual([{ type: 'status', status: 'closed' }]);
  });

  it('does not reactivate or close twice when close races with port opening', async () => {
    const fixture = serialFixture();
    let resolveOpen!: () => void;
    const pendingOpen = new Promise<void>((resolve) => { resolveOpen = resolve; });
    fixture.port.open.mockImplementation(() => pendingOpen);
    const events: TerminalTransportEvent[] = [];
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);

    const opening = transport.open((event) => events.push(event));
    await nextMicrotask();
    const closing = transport.close(Date.now() + 5_000);
    resolveOpen();

    await closing;
    await expect(opening).rejects.toMatchObject({ code: 'port_unavailable' });
    expect(fixture.port.close).toHaveBeenCalledOnce();
    expect(fixture.port.readable.locked).toBe(false);
    expect(fixture.port.writable.locked).toBe(false);
    expect(events).toEqual([{ type: 'status', status: 'closed' }]);
  });

  it('rejects an overflowing write queue before the extra chunk reaches the port', async () => {
    const fixture = serialFixture();
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
    await transport.open(vi.fn());

    const writes = Array.from({ length: 16 }, () => transport.write('x'.repeat(4_096)));
    await expect(transport.write('x'.repeat(4_096))).rejects.toMatchObject({
      code: 'serial_write_queue_full',
    });
    await Promise.all(writes);

    expect(fixture.write).toHaveBeenCalledTimes(16);
    expect(fixture.write.mock.calls.map(([chunk]) => chunk.byteLength))
      .toEqual(Array(16).fill(4_096));
  });

  it('rejects an individual write larger than 4 KiB', async () => {
    const fixture = serialFixture();
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
    await transport.open(vi.fn());

    await expect(transport.write('x'.repeat(4_097))).rejects.toMatchObject({
      code: 'serial_write_queue_full',
    });
    expect(fixture.write).not.toHaveBeenCalled();
  });

  it('releases both stream locks and closes once after user close', async () => {
    const fixture = serialFixture();
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
    await transport.open(vi.fn());
    await transport.close(Date.now() + 5_000);
    expect(fixture.port.readable.locked).toBe(false);
    expect(fixture.port.writable.locked).toBe(false);
    expect(fixture.port.close).toHaveBeenCalledOnce();
  });

  it('requires a fresh transport after close', async () => {
    const fixture = serialFixture();
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
    await transport.open(vi.fn());
    await transport.close(Date.now() + 5_000);

    await expect(transport.open(vi.fn())).rejects.toMatchObject({ code: 'port_unavailable' });
    expect(fixture.requestPort).toHaveBeenCalledOnce();
  });

  it('maps read failure without exposing the raw exception and closes', async () => {
    const fixture = serialFixture();
    const events: TerminalTransportEvent[] = [];
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
    await transport.open((event) => events.push(event));
    fixture.failRead();
    await nextMicrotask();
    await nextMicrotask();
    expect(events).toContainEqual({
      type: 'error', code: 'serial_read_failed', message: 'Serial read failed',
    });
    expect(JSON.stringify(events)).not.toContain('raw serial read detail');
  });

  it('maps write failure without exposing the raw exception and closes', async () => {
    const fixture = serialFixture({
      write: () => Promise.reject(new Error('raw serial write detail')),
    });
    const events: TerminalTransportEvent[] = [];
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
    await transport.open((event) => events.push(event));
    await expect(transport.write('x')).rejects.toMatchObject({ code: 'serial_write_failed' });
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
    const firstAssertion = expect(first).rejects.toMatchObject({ code: 'cleanup_timed_out' });
    const secondAssertion = expect(second).rejects.toMatchObject({ code: 'cleanup_timed_out' });
    await vi.advanceTimersByTimeAsync(5_000);
    await firstAssertion;
    await secondAssertion;
    expect(fixture.removeEventListener).toHaveBeenCalled();
  });

  it('sanitizes a rejected cancellation after the cleanup deadline', async () => {
    const fixture = serialFixture({
      cancel: () => Promise.reject(new Error('raw cancellation detail')),
    });
    const events: TerminalTransportEvent[] = [];
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
    await transport.open((event) => events.push(event));

    await expect(transport.close(Date.now())).rejects.toMatchObject({ code: 'cleanup_timed_out' });
    expect(JSON.stringify(events)).not.toContain('raw cancellation detail');
    expect(fixture.port.close).toHaveBeenCalledOnce();
  });

  it('cleans up after adapter removal during active I/O without reconnecting', async () => {
    vi.useFakeTimers();
    const fixture = serialFixture({ write: () => new Promise<void>(() => undefined) });
    const events: TerminalTransportEvent[] = [];
    const transport = new UsbSerialTransport(fixture.api, defaultSerialSettings);
    await transport.open((event) => events.push(event));
    const write = transport.write('x');
    fixture.disconnect();
    await nextMicrotask();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.runAllTimersAsync();
    await nextMicrotask();

    expect(events).toContainEqual({
      type: 'error', code: 'device_disconnected', message: 'Device disconnected',
    });
    await expect(transport.write('y')).rejects.toMatchObject({ code: 'serial_write_failed' });
    expect(fixture.port.close).toHaveBeenCalledOnce();
    expect(fixture.port.readable.locked).toBe(false);
    expect(fixture.port.writable.locked).toBe(false);
    expect(fixture.requestPort).toHaveBeenCalledOnce();
    void write.catch(() => undefined);
  });
});
