import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TerminalPanel } from '../src/features/inventory/TerminalPanel';
import { TerminalSession } from '../src/features/terminal/TerminalSession';
import type {
  TerminalTransport,
  TerminalTransportEvent,
  TerminalTransportListener,
} from '../src/features/terminal/transport';

const terminalMocks = vi.hoisted(() => ({
  instances: [] as {
    emitInput: (data: string) => void;
    write: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
  }[],
}));

const fitMocks = vi.hoisted(() => ({
  instances: [] as {
    fit: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
  }[],
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
    readonly fit = vi.fn();
    readonly dispose = vi.fn();
    constructor() {
      fitMocks.instances.push({ fit: this.fit, dispose: this.dispose });
    }
  },
}));

class FakeWebSocket {
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];

  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() { return undefined; }
}

class FakeTransport implements TerminalTransport {
  readonly kind = 'usb' as const;
  listener: TerminalTransportListener | undefined;
  readonly open = vi.fn((listener: TerminalTransportListener): Promise<void> => {
    this.listener = listener;
    listener({ type: 'status', status: 'connected' });
    return Promise.resolve();
  });
  readonly write = vi.fn((): Promise<void> => Promise.resolve());
  readonly resize = vi.fn(() => undefined);
  readonly close = vi.fn((): Promise<void> => Promise.resolve());
  emit(event: TerminalTransportEvent) { this.listener?.(event); }
}

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

describe('Direct Mode terminal', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    terminalMocks.instances = [];
    fitMocks.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('keeps SSH raw and sends the existing Direct Mode acknowledgement', async () => {
    const user = userEvent.setup();
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);

    expect(screen.getByText('Direct Mode — no rollback protection')).toBeVisible();
    expect(FakeWebSocket.instances).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: 'I understand — open Direct Mode' }));
    const socket = FakeWebSocket.instances[0];
    expect(socket?.url).toContain('/ws/terminal/2ad0db14-5a87-4147-a4e7-c98f88322464');
    if (socket === undefined) throw new Error('Terminal WebSocket was not created.');
    socket.readyState = FakeWebSocket.OPEN;
    socket.onopen?.();
    terminalMocks.instances[0]?.emitInput('show version\r\nreload');

    expect(socket.sent).toEqual([
      JSON.stringify({ type: 'accept_direct_mode' }),
      JSON.stringify({ type: 'input', data: 'show version\r\nreload' }),
    ]);
    expect(screen.queryByRole('button', { name: /Send \d+ lines/ })).not.toBeInTheDocument();
  });

  it('sends terminal dimensions when the SSH session resizes', async () => {
    const user = userEvent.setup();
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
    await user.click(screen.getByRole('button', { name: 'I understand — open Direct Mode' }));
    const socket = FakeWebSocket.instances[0];
    if (socket === undefined) throw new Error('Expected an SSH WebSocket.');
    socket.readyState = FakeWebSocket.OPEN;

    fireEvent(window, new Event('resize'));

    expect(socket.sent).toContain(JSON.stringify({ type: 'resize', columns: 80, rows: 24 }));
  });

  it.each([
    ['malformed message', (socket: FakeWebSocket) => socket.onmessage?.({ data: 'raw socket detail' }),
      'The terminal server returned an invalid message.'],
    ['socket error', (socket: FakeWebSocket) => socket.onerror?.(),
      'Unable to reach the terminal service.'],
  ])('maps a %s to fixed in-memory copy', async (_case, emit, expected) => {
    const user = userEvent.setup();
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
    await user.click(screen.getByRole('button', { name: 'I understand — open Direct Mode' }));
    const socket = FakeWebSocket.instances[0];
    if (socket === undefined) throw new Error('Expected an SSH WebSocket.');

    act(() => emit(socket));

    expect(await screen.findByRole('alert')).toHaveTextContent(expected);
    expect(screen.queryByText('raw socket detail')).not.toBeInTheDocument();
  });

  it('maps a clean SSH close back to a fresh-session prompt', async () => {
    const user = userEvent.setup();
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
    await user.click(screen.getByRole('button', { name: 'I understand — open Direct Mode' }));
    const socket = FakeWebSocket.instances[0];
    if (socket === undefined) throw new Error('Expected an SSH WebSocket.');

    act(() => socket.onclose?.());

    expect(await screen.findByRole('button', {
      name: 'I understand — open Direct Mode',
    })).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('limits terminal tabs to three', async () => {
    const user = userEvent.setup();
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);

    const add = screen.getByRole('button', { name: 'New terminal' });
    await user.click(add);
    await user.click(add);

    expect(screen.getAllByRole('tab')).toHaveLength(3);
    expect(add).toBeDisabled();
  });

  it('clears a pending multiline confirmation on close', async () => {
    const transport = new FakeTransport();
    const { unmount } = renderUsbLikeSession(transport);
    await userEvent.click(screen.getByRole('button', { name: 'Open test session' }));
    act(() => terminalMocks.instances[0]?.emitInput('show version\r\nreload'));
    expect(screen.getByRole('button', { name: 'Send 2 lines' })).toBeVisible();

    unmount();
    await act(() => Promise.resolve());

    expect(transport.write).not.toHaveBeenCalled();
    expect(transport.close).toHaveBeenCalledOnce();
    expect(terminalMocks.instances[0]?.dispose).toHaveBeenCalledOnce();
    expect(fitMocks.instances[0]?.dispose).toHaveBeenCalledOnce();
  });

  it('sends normalized multiline input and clears its confirmation', async () => {
    const user = userEvent.setup();
    const transport = new FakeTransport();
    renderUsbLikeSession(transport);
    await user.click(screen.getByRole('button', { name: 'Open test session' }));
    act(() => terminalMocks.instances[0]?.emitInput('show version\r\nreload'));

    await user.click(screen.getByRole('button', { name: 'Send 2 lines' }));

    expect(transport.write).toHaveBeenCalledWith('show version\rreload');
    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
  });

  it('cancels pending multiline input without transmitting it', async () => {
    const user = userEvent.setup();
    const transport = new FakeTransport();
    renderUsbLikeSession(transport);
    await user.click(screen.getByRole('button', { name: 'Open test session' }));
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(transport.write).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
  });

  it('clears pending multiline input and sanitizes a write failure', async () => {
    const user = userEvent.setup();
    const transport = new FakeTransport();
    transport.write.mockRejectedValueOnce(new Error('raw browser detail'));
    renderUsbLikeSession(transport);
    await user.click(screen.getByRole('button', { name: 'Open test session' }));
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));

    await user.click(screen.getByRole('button', { name: 'Send 2 lines' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Terminal write failed');
    expect(screen.queryByText('raw browser detail')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
  });

  it('resets after pagehide and reopens with fresh session objects', async () => {
    const user = userEvent.setup();
    const transports: FakeTransport[] = [];
    renderUsbLikeSession(() => {
      const transport = new FakeTransport();
      transports.push(transport);
      return transport;
    });
    await user.click(screen.getByRole('button', { name: 'Open test session' }));
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));

    fireEvent(window, new Event('pagehide'));

    expect(await screen.findByRole('button', { name: 'Open test session' })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
    transports[0]?.emit({ type: 'output', data: 'late output' });
    expect(terminalMocks.instances[0]?.write).not.toHaveBeenCalledWith('late output');

    await user.click(screen.getByRole('button', { name: 'Open test session' }));
    expect(transports).toHaveLength(2);
    expect(terminalMocks.instances).toHaveLength(2);
    expect(transports[1]).not.toBe(transports[0]);
  });

  it('uses transport-neutral copy for authorization-gated sessions', () => {
    render(
      <TerminalSession
        createTransport={() => new FakeTransport()}
        warningTitle="Test Direct Mode"
        warningBody="Test warning"
        acknowledgementLabel="I am authorized to access this device"
        requireAuthorization
        inputPolicy={{ lineEnding: 'cr', localEcho: false, confirmMultiline: true }}
        ariaLabel="Test terminal"
        note="Test session"
      />,
    );

    expect(screen.getByRole('button', { name: 'Open terminal session' })).toBeDisabled();
    expect(screen.queryByText('Open USB Direct Mode')).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: 'Open test session' }));
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }));

    await act(() => vi.advanceTimersByTimeAsync(5_000));

    expect(terminalMocks.instances[0]?.dispose).toHaveBeenCalledOnce();
    expect(fitMocks.instances[0]?.dispose).toHaveBeenCalledOnce();
    expect(screen.getByText('Cleanup timed out')).toBeVisible();
  });

  it('shows cleanup timeout over an earlier transport error and reopens fresh', async () => {
    vi.useFakeTimers();
    const transports: FakeTransport[] = [];
    renderUsbLikeSession(() => {
      const transport = new FakeTransport();
      if (transports.length === 0) {
        transport.close.mockImplementation(() => new Promise<void>(() => undefined));
      }
      transports.push(transport);
      return transport;
    });
    fireEvent.click(screen.getByRole('button', { name: 'Open test session' }));
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));
    expect(screen.getByRole('button', { name: 'Send 2 lines' })).toBeVisible();

    act(() => {
      transports[0]?.emit({
        type: 'error',
        code: 'serial_read_failed',
        message: 'Serial read failed',
      });
    });
    await act(() => vi.advanceTimersByTimeAsync(5_000));

    expect(screen.getByRole('alert')).toHaveTextContent('Cleanup timed out');
    expect(screen.queryByText('Serial read failed')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
    expect(terminalMocks.instances[0]?.dispose).toHaveBeenCalledOnce();
    expect(fitMocks.instances[0]?.dispose).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole('button', { name: 'Open test session' }));
    expect(transports).toHaveLength(2);
    expect(terminalMocks.instances).toHaveLength(2);
    expect(transports[1]).not.toBe(transports[0]);
    expect(terminalMocks.instances[1]).not.toBe(terminalMocks.instances[0]);
  });
});
