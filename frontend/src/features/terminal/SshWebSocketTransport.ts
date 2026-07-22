import type { TerminalTransport, TerminalTransportListener } from './transport';

export class SshWebSocketTransport implements TerminalTransport {
  readonly kind = 'ssh' as const;
  private socket: WebSocket | null = null;
  private closePromise: Promise<void> | null = null;

  constructor(
    private readonly deviceId: string,
    private readonly group1RiskAcknowledged = false,
  ) {}

  open(listener: TerminalTransportListener): Promise<void> {
    listener({ type: 'status', status: 'connecting' });
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.socket = new WebSocket(
      `${protocol}//${window.location.host}/ws/terminal/${encodeURIComponent(this.deviceId)}`,
    );
    this.socket.onopen = () => {
      this.socket?.send(JSON.stringify({
        type: 'accept_direct_mode',
        group1_risk_acknowledged: this.group1RiskAcknowledged,
      }));
    };
    this.socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data)) as Record<string, unknown>;
        if (message.type === 'output' && typeof message.data === 'string') {
          listener({ type: 'output', data: message.data });
        } else if (
          message.type === 'status'
          && (message.status === 'connecting'
            || message.status === 'connected'
            || message.status === 'closed')
        ) {
          listener({ type: 'status', status: message.status });
        } else if (
          message.type === 'error'
          && typeof message.code === 'string'
          && typeof message.message === 'string'
          && typeof message.retryable === 'boolean'
          && (message.phase === undefined || typeof message.phase === 'string')
          && (
            message.recommended_action === undefined
            || typeof message.recommended_action === 'string'
          )
        ) {
          listener({
            type: 'error',
            code: message.code,
            message: message.message,
            retryable: message.retryable,
            ...(typeof message.phase === 'string' ? { phase: message.phase } : {}),
            ...(typeof message.recommended_action === 'string'
              ? { recommendedAction: message.recommended_action }
              : {}),
          });
        } else {
          listener({
            type: 'error',
            code: 'invalid_terminal_message',
            message: 'The terminal server returned an invalid message.',
            retryable: false,
          });
        }
      } catch {
        listener({
          type: 'error',
          code: 'invalid_terminal_message',
          message: 'The terminal server returned an invalid message.',
          retryable: false,
        });
      }
    };
    this.socket.onerror = () => listener({
      type: 'error',
      code: 'terminal_service_unavailable',
      message: 'Unable to reach the terminal service.',
      retryable: true,
    });
    this.socket.onclose = () => listener({ type: 'status', status: 'closed' });
    return Promise.resolve();
  }

  write(data: string): Promise<void> {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'input', data }));
    }
    return Promise.resolve();
  }

  resize(columns: number, rows: number): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'resize', columns, rows }));
    }
  }

  close(): Promise<void> {
    this.closePromise ??= Promise.resolve().then(() => {
      this.socket?.close();
      this.socket = null;
    });
    return this.closePromise;
  }
}
