export const TERMINAL_CLEANUP_TIMEOUT_MS = 5_000;
export const USB_WRITE_CHUNK_LIMIT_BYTES = 4_096;
export const USB_WRITE_QUEUE_LIMIT_BYTES = 65_536;

export type TerminalStatus = 'connecting' | 'connected' | 'closed';

export interface TerminalFailure {
  code: string;
  message: string;
  phase?: string;
  retryable: boolean;
  recommendedAction?: string;
}

export type TerminalTransportEvent =
  | { type: 'output'; data: string }
  | { type: 'status'; status: TerminalStatus }
  | ({ type: 'error' }
    & Omit<TerminalFailure, 'retryable'>
    & Partial<Pick<TerminalFailure, 'retryable'>>);

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
