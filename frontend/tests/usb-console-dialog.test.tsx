import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { InventoryPage } from '../src/features/inventory/InventoryPage';
import { UsbConsoleDialog } from '../src/features/inventory/UsbConsoleDialog';
import type {
  SerialApi,
  UsbSerialCapability,
} from '../src/features/terminal/UsbSerialTransport';
import { nextMicrotask, serialFixture } from './fakes/webSerial';

const terminalMocks = vi.hoisted(() => ({
  instances: [] as {
    emitInput: (data: string) => void;
    write: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
  }[],
}));

const transportMocks = vi.hoisted(() => ({ instances: [] as object[] }));
const originalStorageSetItem = Object.getOwnPropertyDescriptor(Storage.prototype, 'setItem');
const originalSendBeacon = Object.getOwnPropertyDescriptor(navigator, 'sendBeacon');
const originalHistoryPushState = Object.getOwnPropertyDescriptor(history, 'pushState');
const originalHistoryReplaceState = Object.getOwnPropertyDescriptor(history, 'replaceState');

const failFast = (name: string) => vi.fn(() => {
  throw new Error(`USB Direct Mode must not call ${name}`);
});

const guardedStorage = (name: string) => ({
  getItem: failFast(`${name}.getItem`),
  setItem: failFast(`${name}.setItem`),
  removeItem: failFast(`${name}.removeItem`),
  clear: failFast(`${name}.clear`),
  key: failFast(`${name}.key`),
  length: 0,
});

function installUsbPrivacyGuards() {
  const fetchSpy = failFast('fetch');
  const socketSpy = failFast('WebSocket');
  const localStorageGuard = guardedStorage('localStorage');
  const sessionStorageGuard = guardedStorage('sessionStorage');
  const indexedOpen = failFast('indexedDB.open');
  const indexedDeleteDatabase = failFast('indexedDB.deleteDatabase');
  const sendBeacon = failFast('navigator.sendBeacon');
  vi.stubGlobal('fetch', fetchSpy);
  vi.stubGlobal('WebSocket', socketSpy);
  vi.stubGlobal('localStorage', localStorageGuard);
  vi.stubGlobal('sessionStorage', sessionStorageGuard);
  vi.stubGlobal('indexedDB', { open: indexedOpen, deleteDatabase: indexedDeleteDatabase });
  Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: sendBeacon });
  const historyPush = vi.spyOn(history, 'pushState').mockImplementation(() => {
    throw new Error('USB Direct Mode must not call history.pushState');
  });
  const historyReplace = vi.spyOn(history, 'replaceState').mockImplementation(() => {
    throw new Error('USB Direct Mode must not call history.replaceState');
  });
  const reportError = vi.spyOn(console, 'error').mockImplementation(() => {
    throw new Error('USB Direct Mode must not call console.error');
  });
  const spies = [
    fetchSpy,
    socketSpy,
    ...Object.values(localStorageGuard).filter((value) => typeof value === 'function'),
    ...Object.values(sessionStorageGuard).filter((value) => typeof value === 'function'),
    indexedOpen,
    indexedDeleteDatabase,
    sendBeacon,
    historyPush,
    historyReplace,
    reportError,
  ];
  return {
    assertUnused: () => spies.forEach((spy) => expect(spy).not.toHaveBeenCalled()),
  };
}

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
    fit() { return undefined; }
    dispose() { return undefined; }
  },
}));

vi.mock('../src/features/terminal/UsbSerialTransport', async () => {
  const actual = await vi.importActual<
    typeof import('../src/features/terminal/UsbSerialTransport')
  >('../src/features/terminal/UsbSerialTransport');
  return {
    ...actual,
    UsbSerialTransport: class extends actual.UsbSerialTransport {
      constructor(...args: ConstructorParameters<typeof actual.UsbSerialTransport>) {
        super(...args);
        transportMocks.instances.push(this);
      }
    },
  };
});

vi.mock('../src/api/network', async () => {
  const actual = await vi.importActual<typeof import('../src/api/network')>('../src/api/network');
  return {
    ...actual,
    api: {
      ...actual.api,
      devices: vi.fn(),
      credentialProfiles: vi.fn(),
    },
  };
});

const renderDialog = (
  fixture = serialFixture(),
  capability: UsbSerialCapability = { available: true },
) => {
  render(<UsbConsoleDialog serialApi={fixture.api} capability={capability} />);
  return fixture;
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('Manual USB Console', () => {
  beforeEach(() => {
    terminalMocks.instances = [];
    transportMocks.instances = [];
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    if (originalSendBeacon === undefined) {
      Reflect.deleteProperty(navigator, 'sendBeacon');
    } else {
      Object.defineProperty(navigator, 'sendBeacon', originalSendBeacon);
    }
  });

  it('requires authorization acknowledgement before requesting a port', async () => {
    const fixture = renderDialog();
    expect(screen.getByText(/can modify, restart, or erase/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Open USB Direct Mode' })).toBeDisabled();

    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));

    expect(fixture.requestPort).toHaveBeenCalledOnce();
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
      baudRate: 250000,
      dataBits: 8,
      stopBits: 1,
      parity: 'none',
      flowControl: 'none',
    });

    act(() => terminalMocks.instances[0]?.emitInput('show version\r\nreload'));
    expect(screen.getByRole('alert')).toHaveTextContent('2 lines are waiting');
    expect(fixture.write).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Send 2 lines' }));
    await waitFor(() => expect(fixture.write).toHaveBeenCalledOnce());
    expect(fixture.write.mock.calls[0]?.[0]).toEqual(
      new TextEncoder().encode('show version\r\nreload'),
    );
    expect(terminalMocks.instances[0]?.write).toHaveBeenCalledWith('show version\r\nreload');
  });

  it.each([
    ['browser_unsupported' as const, 'Chrome or Edge is required'],
    ['secure_context_required' as const, 'A secure context is required'],
    ['serial_policy_blocked' as const, 'Serial access is blocked by policy'],
  ])('renders sanitized capability state %s without requesting a port', (code, message) => {
    const fixture = renderDialog(serialFixture(), { available: false, code });
    expect(screen.getByText(message)).toBeVisible();
    expect(fixture.requestPort).not.toHaveBeenCalled();
  });

  it('creates no REST, WebSocket, storage, IndexedDB, analytics, or reporting traffic', async () => {
    const privacy = installUsbPrivacyGuards();
    const fixture = renderDialog();
    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
    fixture.enqueue(new TextEncoder().encode('ready'));
    await nextMicrotask();
    await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }));

    const denied = serialFixture();
    denied.requestPort.mockRejectedValueOnce(
      new DOMException('raw browser detail', 'NotAllowedError'),
    );
    cleanup();
    renderDialog(denied);
    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
    expect(await screen.findByText('Permission denied')).toBeVisible();
    expect(screen.queryByText('raw browser detail')).not.toBeInTheDocument();
    privacy.assertUnused();
  });

  it('keeps a serial read failure sanitized, in memory, and private', async () => {
    const privacy = installUsbPrivacyGuards();
    const fixture = renderDialog();
    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));

    act(() => fixture.failRead());

    expect(await screen.findByText('Serial read failed')).toBeVisible();
    expect(screen.queryByText('raw serial read detail')).not.toBeInTheDocument();
    privacy.assertUnused();
  });

  it('keeps a serial write failure sanitized, in memory, and private', async () => {
    const privacy = installUsbPrivacyGuards();
    const fixture = renderDialog(serialFixture({
      write: () => Promise.reject(new Error('raw serial write detail')),
    }));
    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));

    act(() => terminalMocks.instances[0]?.emitInput('show version'));

    expect(await screen.findByText('Serial write failed')).toBeVisible();
    expect(screen.queryByText('raw serial write detail')).not.toBeInTheDocument();
    expect(fixture.write).toHaveBeenCalledOnce();
    privacy.assertUnused();
  });

  it('keeps adapter removal sanitized, in memory, and private', async () => {
    const privacy = installUsbPrivacyGuards();
    const fixture = renderDialog();
    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));

    await act(() => fixture.disconnect());

    expect(await screen.findByText('Device disconnected')).toBeVisible();
    privacy.assertUnused();
  });

  it('keeps cleanup timeout private and reopens with fresh objects', async () => {
    vi.useFakeTimers();
    const privacy = installUsbPrivacyGuards();
    const first = serialFixture({ cancel: () => new Promise<void>(() => undefined) });
    const second = serialFixture();
    const requestPort = vi.fn()
      .mockResolvedValueOnce(first.port)
      .mockResolvedValueOnce(second.port);
    const serialApi: SerialApi = { requestPort };
    render(<UsbConsoleDialog serialApi={serialApi} capability={{ available: true }} />);
    fireEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
    await act(nextMicrotask);
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }));

    await act(() => vi.advanceTimersByTimeAsync(5_000));

    expect(screen.getByText('Cleanup timed out')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Open USB Direct Mode' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
    await act(nextMicrotask);
    expect(requestPort).toHaveBeenCalledTimes(2);
    expect(transportMocks.instances).toHaveLength(2);
    expect(terminalMocks.instances).toHaveLength(2);
    expect(transportMocks.instances[1]).not.toBe(transportMocks.instances[0]);
    expect(terminalMocks.instances[1]).not.toBe(terminalMocks.instances[0]);
    privacy.assertUnused();
  });

  it('does not leak browser API mocks from the privacy check', () => {
    expect(Object.getOwnPropertyDescriptor(Storage.prototype, 'setItem')).toEqual(
      originalStorageSetItem,
    );
    expect(Object.getOwnPropertyDescriptor(navigator, 'sendBeacon')).toEqual(originalSendBeacon);
    expect(Object.getOwnPropertyDescriptor(history, 'pushState')).toEqual(originalHistoryPushState);
    expect(Object.getOwnPropertyDescriptor(history, 'replaceState')).toEqual(
      originalHistoryReplaceState,
    );
  });

  it('resets authorization and settings and creates fresh objects after close', async () => {
    const first = serialFixture();
    const second = serialFixture();
    const requestPort = vi.fn()
      .mockResolvedValueOnce(first.port)
      .mockResolvedValueOnce(second.port);
    const api: SerialApi = { requestPort };
    render(<UsbConsoleDialog serialApi={api} capability={{ available: true }} />);
    await userEvent.selectOptions(screen.getByLabelText('Baud rate'), '115200');
    await userEvent.selectOptions(screen.getByLabelText('Line ending'), 'lf');
    await userEvent.click(screen.getByRole('checkbox', { name: 'Local echo' }));
    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
    await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }));

    expect(await screen.findByLabelText('Baud rate')).toHaveValue('9600');
    expect(screen.getByLabelText('Line ending')).toHaveValue('cr');
    expect(screen.getByRole('checkbox', { name: 'Local echo' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: /authorized to access/ })).not.toBeChecked();

    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
    expect(transportMocks.instances).toHaveLength(2);
    expect(terminalMocks.instances).toHaveLength(2);
    expect(transportMocks.instances[1]).not.toBe(transportMocks.instances[0]);
    expect(terminalMocks.instances[1]).not.toBe(terminalMocks.instances[0]);
  });

  it('returns to sanitized idle state after adapter removal and can reopen', async () => {
    const first = serialFixture();
    const second = serialFixture();
    const requestPort = vi.fn()
      .mockResolvedValueOnce(first.port)
      .mockResolvedValueOnce(second.port);
    const api: SerialApi = { requestPort };
    render(<UsbConsoleDialog serialApi={api} capability={{ available: true }} />);
    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
    await act(() => first.disconnect());

    expect(await screen.findByText('Device disconnected')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Open USB Direct Mode' })).toBeDisabled();
    await userEvent.click(screen.getByRole('checkbox', { name: /authorized to access/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Open USB Direct Mode' }));
    expect(requestPort).toHaveBeenCalledTimes(2);
  });

  it('is available before the first device is registered', async () => {
    vi.mocked(api.devices).mockResolvedValue([]);
    vi.mocked(api.credentialProfiles).mockResolvedValue([]);
    render(<InventoryPage />, { wrapper: TestProviders });

    const openConsole = await screen.findByRole('button', { name: 'Open USB Console' });
    const addDevice = await screen.findByRole('button', { name: 'Add first device' });
    expect(openConsole).toBeVisible();
    expect(openConsole.compareDocumentPosition(addDevice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
