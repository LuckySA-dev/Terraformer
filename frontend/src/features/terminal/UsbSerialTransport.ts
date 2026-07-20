import {
  TERMINAL_CLEANUP_TIMEOUT_MS,
  TerminalTransportError,
  USB_WRITE_CHUNK_LIMIT_BYTES,
  USB_WRITE_QUEUE_LIMIT_BYTES,
  type TerminalTransport,
  type TerminalTransportListener,
} from './transport';

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

async function settleBefore(promise: Promise<unknown>, deadlineAt: number): Promise<boolean> {
  const remaining = Math.max(0, deadlineAt - Date.now());
  if (remaining === 0) {
    void promise.catch(() => undefined);
    return false;
  }
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

export class UsbSerialTransport implements TerminalTransport {
  readonly kind = 'usb' as const;
  private port: SerialPortLike | null = null;
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private writer: WritableStreamDefaultWriter<Uint8Array> | null = null;
  private decoder: TextDecoder | null = null;
  private listener: TerminalTransportListener | null = null;
  private readLoop: Promise<void> | null = null;
  private writeTail: Promise<void> = Promise.resolve();
  private pendingWriteBytes = 0;
  private closePromise: Promise<void> | null = null;
  private closing = false;
  private disposed = false;
  private readonly onDisconnect = () => {
    if (this.closing || this.disposed) return;
    this.fail('device_disconnected', 'Device disconnected');
  };

  constructor(
    private readonly api: SerialApi,
    private readonly settings: UsbSerialSettings,
  ) {}

  async open(listener: TerminalTransportListener): Promise<void> {
    this.listener = listener;
    if (this.disposed || this.closing || this.port !== null) {
      throw new TerminalTransportError('port_unavailable', 'Port unavailable');
    }
    const requestedPort = this.api.requestPort();
    try {
      const port = await requestedPort;
      this.port = port;
      port.addEventListener('disconnect', this.onDisconnect);
      await port.open(this.settings);
      const reader = port.readable?.getReader() ?? null;
      const writer = port.writable?.getWriter() ?? null;
      if (reader === null || writer === null) {
        reader?.releaseLock();
        writer?.releaseLock();
        throw new TerminalTransportError('port_unavailable', 'Port unavailable');
      }
      this.reader = reader;
      this.writer = writer;
      this.decoder = new TextDecoder();
      listener({ type: 'status', status: 'connected' });
      this.readLoop = this.read();
    } catch (error) {
      if (error instanceof DOMException && error.name === 'NotFoundError') {
        listener({ type: 'status', status: 'closed' });
        return;
      }
      const mapped = this.openFailure(error);
      listener({ type: 'error', code: mapped.code, message: mapped.message });
      try {
        await this.close(Date.now() + TERMINAL_CLEANUP_TIMEOUT_MS);
      } catch {
        // The event is sanitized above; cleanup errors are not reported twice here.
      }
      throw mapped;
    }
  }

  async write(data: string): Promise<void> {
    if (this.closing || this.writer === null) {
      throw new TerminalTransportError('serial_write_failed', 'Serial write failed');
    }
    const bytes = new TextEncoder().encode(data);
    if (
      bytes.byteLength > USB_WRITE_CHUNK_LIMIT_BYTES
      || this.pendingWriteBytes + bytes.byteLength > USB_WRITE_QUEUE_LIMIT_BYTES
    ) {
      const error = new TerminalTransportError(
        'serial_write_queue_full',
        'Serial write queue full',
      );
      this.listener?.({ type: 'error', code: error.code, message: error.message });
      void this.close(Date.now() + TERMINAL_CLEANUP_TIMEOUT_MS).catch(() => undefined);
      throw error;
    }
    this.pendingWriteBytes += bytes.byteLength;
    const writer = this.writer;
    const operation = this.writeTail.then(async () => {
      try {
        await writer.write(bytes);
      } catch {
        const error = new TerminalTransportError('serial_write_failed', 'Serial write failed');
        this.fail(error.code, error.message);
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

  resize(): void {
    return undefined;
  }

  close(deadlineAt: number): Promise<void> {
    if (this.closePromise !== null) return this.closePromise;
    this.closing = true;
    this.closePromise = this.cleanup(deadlineAt);
    return this.closePromise;
  }

  private async read(): Promise<void> {
    try {
      while (!this.closing && this.reader !== null) {
        const { value, done } = await this.reader.read();
        if (done) break;
        if (value.byteLength > 0) {
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

  private fail(code: string, message: string): void {
    if (this.closing || this.disposed) return;
    this.listener?.({ type: 'error', code, message });
    void this.close(Date.now() + TERMINAL_CLEANUP_TIMEOUT_MS).catch(() => undefined);
  }

  private openFailure(error: unknown): TerminalTransportError {
    if (error instanceof DOMException) {
      if (error.name === 'NotAllowedError') {
        return new TerminalTransportError('permission_denied', 'Permission denied');
      }
      if (error.name === 'SecurityError') {
        return new TerminalTransportError('serial_access_blocked', 'Serial access blocked');
      }
    }
    return new TerminalTransportError('port_unavailable', 'Port unavailable');
  }

  private async cleanup(deadlineAt: number): Promise<void> {
    const port = this.port;
    const reader = this.reader;
    const writer = this.writer;
    const readLoop = this.readLoop;
    const listener = this.listener;
    let timedOut = false;

    this.port = null;
    this.reader = null;
    this.writer = null;
    this.decoder = null;
    this.readLoop = null;
    this.pendingWriteBytes = 0;
    this.listener = null;
    if (port !== null) port.removeEventListener('disconnect', this.onDisconnect);

    if (reader !== null) {
      try {
        timedOut = !(await settleBefore(reader.cancel(), deadlineAt)) || timedOut;
      } catch {
        // Browser cleanup failures are intentionally ignored after sanitization.
      } finally {
        if (readLoop !== null) {
          timedOut = !(await settleBefore(readLoop, deadlineAt)) || timedOut;
        }
        try {
          reader.releaseLock();
        } catch {
          // Releasing an already-detached reader is harmless.
        }
      }
    }

    if (writer !== null) {
      try {
        const writesSettled = await settleBefore(this.writeTail, deadlineAt);
        timedOut = !writesSettled || timedOut;
        if (!writesSettled) {
          timedOut = !(await settleBefore(writer.abort(), deadlineAt)) || timedOut;
        }
      } catch {
        // Browser cleanup failures are intentionally ignored after sanitization.
      } finally {
        try {
          writer.releaseLock();
        } catch {
          // Releasing an already-detached writer is harmless.
        }
      }
    }

    if (port !== null) {
      try {
        timedOut = !(await settleBefore(port.close(), deadlineAt)) || timedOut;
      } catch {
        // Browser cleanup failures are intentionally ignored after sanitization.
      }
    }

    listener?.({ type: 'status', status: 'closed' });
    this.disposed = true;
    if (timedOut) {
      throw new TerminalTransportError('cleanup_timed_out', 'Cleanup timed out');
    }
    this.closing = false;
  }
}
