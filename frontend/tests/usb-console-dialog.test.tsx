import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
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
    const fetchSpy = vi.fn();
    const socketSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    vi.stubGlobal('WebSocket', socketSpy);
    const storageSet = vi.spyOn(Storage.prototype, 'setItem');
    const indexedOpen = vi.fn();
    vi.stubGlobal('indexedDB', { open: indexedOpen });
    const sendBeacon = vi.fn();
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: sendBeacon });
    const historyPush = vi.spyOn(history, 'pushState');
    const historyReplace = vi.spyOn(history, 'replaceState');
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
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(socketSpy).not.toHaveBeenCalled();
    expect(storageSet).not.toHaveBeenCalled();
    expect(indexedOpen).not.toHaveBeenCalled();
    expect(sendBeacon).not.toHaveBeenCalled();
    expect(historyPush).not.toHaveBeenCalled();
    expect(historyReplace).not.toHaveBeenCalled();
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
