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
  readonly open = vi.fn(() => Promise.resolve());
  readonly close = vi.fn(() => Promise.resolve());

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
  const requestPort = vi.fn(() => Promise.resolve(port));
  const api: SerialApi = { requestPort };
  return {
    api,
    requestPort,
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
