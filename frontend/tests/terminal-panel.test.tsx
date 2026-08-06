import { act, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import userEvent from '@testing-library/user-event';
import { TerminalPanel } from '../src/features/inventory/TerminalPanel';
import { TerminalSession } from '../src/features/terminal/TerminalSession';
import type {
  TerminalTransport,
  TerminalTransportEvent,
  TerminalTransportListener,
} from '../src/features/terminal/transport';

const terminalMocks = vi.hoisted(() => ({
  options: [] as unknown[],
  instances: [] as {
    emitInput: (data: string) => void;
    write: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
    loadAddon: ReturnType<typeof vi.fn>;
    onTitleChange: ReturnType<typeof vi.fn>;
    registerLinkProvider: ReturnType<typeof vi.fn>;
    registerOscHandler: ReturnType<typeof vi.fn>;
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
    readonly loadAddon = vi.fn();
    readonly onTitleChange = vi.fn();
    readonly registerLinkProvider = vi.fn();
    readonly parser = { registerOscHandler: vi.fn() };
    constructor(options: unknown) {
      terminalMocks.options.push(options);
      terminalMocks.instances.push({
        emitInput: (data: string) => this.input(data),
        write: this.write,
        dispose: this.dispose,
        loadAddon: this.loadAddon,
        onTitleChange: this.onTitleChange,
        registerLinkProvider: this.registerLinkProvider,
        registerOscHandler: this.parser.registerOscHandler,
      });
    }
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

  readonly close = vi.fn(() => undefined);
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
  active = true,
  lineEnding: 'cr' | 'lf' | 'crlf' = 'cr',
) => render(
  <TerminalSession
    createTransport={typeof value === 'function' ? value : () => value}
    warningTitle="Test Direct Mode"
    warningBody="Test warning"
    acknowledgementLabel="Open test session"
    inputPolicy={{ lineEnding, localEcho: false, confirmMultiline: true }}
    ariaLabel="Test terminal"
    note="Test session"
    active={active}
  />,
);

describe('Direct Mode terminal', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    terminalMocks.instances = [];
    terminalMocks.options = [];
    fitMocks.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('keeps SSH raw, confirms multiline input, and acknowledges Group1 only on open', async () => {
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
    const commandMarker = 'PRIVATE_COMMAND_7F3A';
    act(() => terminalMocks.instances[0]?.emitInput(`${commandMarker}\r\nreload`));

    expect(socket.sent).toEqual([
      JSON.stringify({ type: 'accept_direct_mode', group1_risk_acknowledged: false }),
    ]);
    expect(screen.getByText('2 lines and 28 characters are waiting. Review before sending.'))
      .toBeVisible();
    expect(document.body.textContent).not.toContain(commandMarker);
    await user.click(screen.getByRole('button', { name: 'Send 2 lines' }));
    expect(socket.sent).toEqual([
      JSON.stringify({ type: 'accept_direct_mode', group1_risk_acknowledged: false }),
      JSON.stringify({ type: 'input', data: `${commandMarker}\r\nreload` }),
    ]);
  });

  it('requires a fresh Group1 risk acknowledgment and sends it only on open', async () => {
    const user = userEvent.setup();
    render(
      <TerminalPanel
        deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464"
        sshCompatibility="cisco_legacy_group1"
      />,
    );
    const openButton = screen.getByRole('button', { name: /open Direct Mode/ });
    const acknowledgement = screen.getByRole('checkbox', { name: /Group1.*last-resort/ });
    expect(acknowledgement).not.toBeChecked();
    expect(openButton).toBeDisabled();
    await user.click(acknowledgement);
    await user.click(openButton);
    const socket = FakeWebSocket.instances[0];
    if (socket === undefined) throw new Error('Expected an SSH WebSocket.');
    socket.readyState = FakeWebSocket.OPEN;
    socket.onopen?.();
    terminalMocks.instances[0]?.emitInput('show version');

    expect(socket.sent).toEqual([
      JSON.stringify({ type: 'accept_direct_mode', group1_risk_acknowledged: true }),
      JSON.stringify({ type: 'input', data: 'show version' }),
    ]);

    act(() => socket.onclose?.());
    expect(await screen.findByRole('checkbox', { name: /Group1.*last-resort/ }))
      .not.toBeChecked();
  });

  it('clears a checked Group1 acknowledgment on tab switch', async () => {
    const user = userEvent.setup();
    render(
      <TerminalPanel
        deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464"
        sshCompatibility="cisco_legacy_group1"
      />,
    );
    await user.click(screen.getByRole('checkbox', { name: /Group1.*last-resort/ }));
    await user.click(screen.getByRole('button', { name: 'New terminal' }));
    await user.click(screen.getByRole('tab', { name: 'Terminal 1' }));

    expect(screen.getByRole('checkbox', { name: /Group1.*last-resort/ })).not.toBeChecked();
  });

  it('constructs xterm with privileged APIs disabled and registers no handlers', async () => {
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
    await userEvent.click(screen.getByRole('button', { name: /open Direct Mode/ }));

    expect(terminalMocks.options[0]).toMatchObject({
      allowProposedApi: false,
      windowOptions: {},
      linkHandler: null,
    });
    expect(terminalMocks.instances[0]?.loadAddon).toHaveBeenCalledOnce();
    expect(terminalMocks.instances[0]?.onTitleChange).not.toHaveBeenCalled();
    expect(terminalMocks.instances[0]?.registerLinkProvider).not.toHaveBeenCalled();
    expect(terminalMocks.instances[0]?.registerOscHandler).not.toHaveBeenCalled();
  });

  it('does not persist terminal data or invoke privileged browser APIs', async () => {
    const fetchSpy = vi.fn();
    const clipboardSpy = vi.fn();
    const notificationSpy = vi.fn();
    const indexedDbSpy = vi.fn();
    const analyticsSpy = vi.fn();
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem');
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    const downloadSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click');
    const navigatorStub = Object.create(navigator) as Navigator;
    Object.defineProperty(navigatorStub, 'clipboard', {
      configurable: true,
      value: { writeText: clipboardSpy },
    });
    vi.stubGlobal('fetch', fetchSpy);
    vi.stubGlobal('navigator', navigatorStub);
    vi.stubGlobal('Notification', notificationSpy);
    vi.stubGlobal('indexedDB', { open: indexedDbSpy });
    vi.stubGlobal('gtag', analyticsSpy);
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
    await userEvent.click(screen.getByRole('button', { name: /open Direct Mode/ }));
    const socket = FakeWebSocket.instances[0];
    if (socket === undefined) throw new Error('Expected an SSH WebSocket.');

    act(() => socket.onmessage?.({
      data: JSON.stringify({ type: 'output', data: '\u001b]8;;https://invalid.example\u0007link' }),
    }));
    act(() => socket.onmessage?.({ data: JSON.stringify({
      type: 'error',
      code: 'device_authentication_failed',
      message: 'Device authentication failed.',
      phase: 'authentication',
      retryable: false,
    }) }));

    expect(terminalMocks.instances[0]?.write).toHaveBeenCalledOnce();
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(storageSpy).not.toHaveBeenCalled();
    expect(indexedDbSpy).not.toHaveBeenCalled();
    expect(analyticsSpy).not.toHaveBeenCalled();
    expect(openSpy).not.toHaveBeenCalled();
    expect(clipboardSpy).not.toHaveBeenCalled();
    expect(notificationSpy).not.toHaveBeenCalled();
    expect(downloadSpy).not.toHaveBeenCalled();
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

  it('exposes selected terminal tabs and close labels', async () => {
    const user = userEvent.setup();
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);

    const first = screen.getByRole('tab', { name: 'Terminal 1' });
    expect(first).toHaveAttribute('aria-selected', 'true');
    first.focus();
    expect(first).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Close terminal 1' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'New terminal' }));
    expect(first).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByRole('tab', { name: 'Terminal 2' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('button', { name: 'Close terminal 2' })).toBeVisible();
  });

  it('uses the terminal workspace layout without horizontal page overflow', () => {
    const styles = readFileSync('src/styles.css', 'utf8');

    expect(styles).toContain(`.workspace-layout:has(> .inspector--terminal) {
  grid-template-columns: minmax(0, 1fr) min(680px, 48vw);
}`);
    expect(styles).toContain(`.terminal-session__canvas {
  height: clamp(360px, 55vh, 620px);`);
    expect(styles).toContain(`@media (max-width: 1020px) {
  .inspector--terminal {
    width: min(680px, calc(100vw - 74px));
  }
}`);
    expect(styles).toContain('grid-template-columns: repeat(7, minmax(0, 1fr));');
    expect(styles).toContain('.terminal-tabs {\n  display: flex;\n  align-items: center;\n  gap: 5px;\n  overflow-x: auto;');
  });

  it('clears pending input when switching tabs without closing either transport', async () => {
    const user = userEvent.setup();
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
    await user.click(screen.getByRole('button', { name: /open Direct Mode/ }));
    const firstSocket = FakeWebSocket.instances[0];
    if (firstSocket === undefined) throw new Error('Expected an SSH WebSocket.');
    firstSocket.readyState = FakeWebSocket.OPEN;
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));
    expect(screen.getByRole('button', { name: 'Send 2 lines' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'New terminal' }));
    act(() => terminalMocks.instances[0]?.emitInput('stale\ninput'));
    await user.click(screen.getByRole('tab', { name: 'Terminal 1' }));

    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
    expect(firstSocket.close).not.toHaveBeenCalled();
  });

  it('clears pending input when removing a tab', async () => {
    const user = userEvent.setup();
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
    await user.click(screen.getByRole('button', { name: /open Direct Mode/ }));
    const socket = FakeWebSocket.instances[0];
    if (socket === undefined) throw new Error('Expected an SSH WebSocket.');
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));
    expect(screen.getByRole('button', { name: 'Send 2 lines' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Close terminal 1' }));
    await act(() => Promise.resolve());

    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
    expect(socket.close).toHaveBeenCalledOnce();
  });

  it('accepts 4,096 prepared bytes and rejects 4,097 before buffering or writing', async () => {
    const transport = new FakeTransport();
    renderUsbLikeSession(transport, true, 'crlf');
    await userEvent.click(screen.getByRole('button', { name: 'Open test session' }));

    act(() => terminalMocks.instances[0]?.emitInput(
      `${'x'.repeat(2_047)}\n${'y'.repeat(2_047)}`,
    ));
    expect(screen.getByRole('button', { name: 'Send 2 lines' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    act(() => terminalMocks.instances[0]?.emitInput(
      `${'x'.repeat(2_047)}\n${'y'.repeat(2_048)}`,
    ));

    expect(screen.getByRole('alert')).toHaveTextContent('Terminal input is too large.');
    expect(screen.queryByRole('button', { name: /Send/ })).not.toBeInTheDocument();
    expect(transport.write).not.toHaveBeenCalled();
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

  it('clears pending input after an open failure', async () => {
    const transport = new FakeTransport();
    transport.open.mockRejectedValueOnce(new Error('raw browser detail'));
    renderUsbLikeSession(transport);
    await userEvent.click(screen.getByRole('button', { name: 'Open test session' }));
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to open the terminal session.');
    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
  });

  it('clears pending input on disconnect', async () => {
    const transport = new FakeTransport();
    renderUsbLikeSession(transport);
    await userEvent.click(screen.getByRole('button', { name: 'Open test session' }));
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));

    await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }));

    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
    expect(transport.write).not.toHaveBeenCalled();
  });

  it('retries a retryable failure with fresh WebSocket and xterm objects', async () => {
    const user = userEvent.setup();
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
    await user.click(screen.getByRole('button', { name: /open Direct Mode/ }));
    const firstSocket = FakeWebSocket.instances[0];
    if (firstSocket === undefined) throw new Error('Expected an SSH WebSocket.');
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));
    expect(screen.getByRole('button', { name: 'Send 2 lines' })).toBeVisible();
    act(() => firstSocket.onmessage?.({ data: JSON.stringify({
      type: 'error',
      code: 'device_connection_timeout',
      message: 'The device connection timed out.',
      phase: 'tcp_connection',
      retryable: true,
      recommended_action: 'Try the connection again.',
    }) }));

    await user.click(await screen.findByRole('button', { name: 'Retry' }));

    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(terminalMocks.instances).toHaveLength(2);
    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
    expect(firstSocket.close).toHaveBeenCalledOnce();
    act(() => firstSocket.onmessage?.({ data: JSON.stringify({ type: 'output', data: 'late output' }) }));
    expect(terminalMocks.instances[1]?.write).not.toHaveBeenCalledWith('late output');
  });

  it('shows fixed guidance without Retry for a non-retryable failure', async () => {
    render(<TerminalPanel deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464" />);
    await userEvent.click(screen.getByRole('button', { name: /open Direct Mode/ }));
    const socket = FakeWebSocket.instances[0];
    if (socket === undefined) throw new Error('Expected an SSH WebSocket.');
    act(() => socket.onmessage?.({ data: JSON.stringify({
      type: 'error',
      code: 'device_authentication_failed',
      message: 'Device authentication failed.',
      phase: 'authentication',
      retryable: false,
      recommended_action: 'Verify the selected credential profile and device login policy.',
    }) }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Device authentication failed.');
    expect(screen.getByText('Verify the selected credential profile and device login policy.'))
      .toBeVisible();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('requires fresh Group1 acknowledgment before Retry opens a new session', async () => {
    const user = userEvent.setup();
    render(
      <TerminalPanel
        deviceId="2ad0db14-5a87-4147-a4e7-c98f88322464"
        sshCompatibility="cisco_legacy_group1"
      />,
    );
    await user.click(screen.getByRole('checkbox', { name: /Group1.*last-resort/ }));
    await user.click(screen.getByRole('button', { name: /open Direct Mode/ }));
    const firstSocket = FakeWebSocket.instances[0];
    if (firstSocket === undefined) throw new Error('Expected an SSH WebSocket.');
    firstSocket.readyState = FakeWebSocket.OPEN;
    firstSocket.onopen?.();
    act(() => firstSocket.onmessage?.({ data: JSON.stringify({
      type: 'error',
      code: 'device_connection_timeout',
      message: 'The device connection timed out.',
      phase: 'tcp_connection',
      retryable: true,
    }) }));

    const retry = await screen.findByRole('button', { name: 'Retry' });
    const acknowledgement = screen.getByRole('checkbox', { name: /Group1.*last-resort/ });
    expect(acknowledgement).not.toBeChecked();
    expect(retry).toBeDisabled();
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(terminalMocks.instances).toHaveLength(1);

    await user.click(acknowledgement);
    await user.click(retry);

    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(terminalMocks.instances).toHaveLength(2);
    const secondSocket = FakeWebSocket.instances[1];
    if (secondSocket === undefined) throw new Error('Expected a fresh SSH WebSocket.');
    expect(secondSocket).not.toBe(firstSocket);
    secondSocket.readyState = FakeWebSocket.OPEN;
    secondSocket.onopen?.();
    expect(firstSocket.sent).toEqual([
      JSON.stringify({ type: 'accept_direct_mode', group1_risk_acknowledged: true }),
    ]);
    expect(secondSocket.sent).toEqual([
      JSON.stringify({ type: 'accept_direct_mode', group1_risk_acknowledged: true }),
    ]);
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
    act(() => terminalMocks.instances[0]?.emitInput('show version\nreload'));
    expect(screen.getByRole('button', { name: 'Send 2 lines' })).toBeVisible();

    transports[0]?.emit({ type: 'status', status: 'closed' });
    await userEvent.click(await screen.findByRole('button', { name: 'Open test session' }));

    expect(transports).toHaveLength(2);
    expect(terminalMocks.instances).toHaveLength(2);
    expect(transports[1]).not.toBe(transports[0]);
    expect(screen.queryByRole('button', { name: 'Send 2 lines' })).not.toBeInTheDocument();
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
