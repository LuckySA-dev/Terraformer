import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TerminalPanel } from '../src/features/inventory/TerminalPanel';

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    cols = 80;
    rows = 24;
    loadAddon() { return undefined; }
    open() { return undefined; }
    write() { return undefined; }
    dispose() { return undefined; }
    onData() {
      return { dispose() { return undefined; } };
    }
  },
}));

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit() { return undefined; }
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

describe('Direct Mode terminal', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not connect until the operator accepts Direct Mode', async () => {
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

    expect(socket.sent).toEqual([JSON.stringify({ type: 'accept_direct_mode' })]);
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
});
