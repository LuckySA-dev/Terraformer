import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { DeviceInspector } from '../src/features/inventory/DeviceInspector';
import type { ConfigSnapshot, Device } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    facts: vi.fn(),
    interfaces: vi.fn(),
    snapshots: vi.fn(),
    snapshot: vi.fn(),
    events: vi.fn(),
    testDeviceConnection: vi.fn(),
    refreshDevice: vi.fn(),
    captureSnapshot: vi.fn(),
    job: vi.fn(),
  },
}));

const device: Device = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Generic edge',
  management_address: '192.0.2.20',
  port: 22,
  vendor: 'generic',
  credential_profile_id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
  status: 'reachable',
  facts: { hostname: 'edge-01', uptime: '9 days, 04:12:11' },
  capabilities: [{ name: 'connect', supported: true, safety_level: 'D' }],
  last_seen_at: '2026-07-11T09:00:00Z',
  last_error_code: null,
  created_at: '2026-07-11T08:00:00Z',
  updated_at: '2026-07-11T09:00:00Z',
};

const snapshot: ConfigSnapshot = {
  id: '17b31c79-8e8e-489b-9862-a398f42fa7e6',
  device_id: device.id,
  sha256: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
  plaintext_size: 100,
  compressed_size: 80,
  ciphertext_size: 96,
  compression: 'gzip',
  encryption: 'AES-256-GCM',
  source: 'running-config',
  created_at: '2026-07-11T09:30:00Z',
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderInspector() {
  render(
    <DeviceInspector device={device} onClose={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} />,
    { wrapper: TestProviders },
  );
}

describe('DeviceInspector API contract and safety states', () => {
  beforeEach(() => {
    vi.mocked(api.facts).mockResolvedValue({
      device_id: device.id,
      facts: { hostname: 'edge-01', model: 'Unknown', uptime: '9 days, 04:12:11' },
      last_seen_at: '2026-07-11T09:00:00Z',
    });
    vi.mocked(api.interfaces).mockResolvedValue([]);
    vi.mocked(api.snapshots).mockResolvedValue([]);
    vi.mocked(api.events).mockResolvedValue([]);
  });

  it('renders raw observed uptime, capability arrays, and honest Generic driver scope', async () => {
    renderInspector();

    expect(await screen.findByText('9 days, 04:12:11')).toBeVisible();
    expect(screen.getByText('Generic · connection test only')).toBeVisible();
    expect(screen.getByText('Available · Level D')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Configuration is unavailable' })).toBeVisible();
  });

  it('uses admin_up and oper_up interface fields', async () => {
    const user = userEvent.setup();
    vi.mocked(api.interfaces).mockResolvedValue([
      {
        id: '1ddbdac3-5c7d-44db-8173-a2d61491bb34',
        device_id: device.id,
        name: 'GigabitEthernet1',
        description: 'Management',
        admin_up: false,
        oper_up: false,
        mac_address: null,
        ipv4_addresses: ['192.0.2.20/24'],
        speed_mbps: 1000,
        created_at: '2026-07-11T09:00:00Z',
        updated_at: '2026-07-11T09:00:00Z',
      },
    ]);
    renderInspector();

    await user.click(screen.getByRole('button', { name: 'Interfaces' }));
    expect(await screen.findByText('GigabitEthernet1')).toBeVisible();
    expect(screen.getByText('disabled')).toBeVisible();
    expect(screen.getByText('1000 Mb/s')).toBeVisible();
  });

  it('warns before showing decrypted snapshot content that may contain secrets', async () => {
    const user = userEvent.setup();
    vi.mocked(api.snapshots).mockResolvedValue([snapshot]);
    vi.mocked(api.snapshot).mockResolvedValue({
      ...snapshot,
      content: 'hostname edge-01\n! encrypted local content',
    });
    renderInspector();

    await user.click(screen.getByRole('button', { name: 'Snapshots' }));
    const hash = await screen.findByText(/abcdef123456/);
    const snapshotButton = hash.closest('button');
    if (snapshotButton === null) throw new Error('Snapshot row button was not rendered.');
    await user.click(snapshotButton);

    expect(await screen.findByText('Sensitive local configuration')).toBeVisible();
    expect(screen.getByText(/Do not copy it into logs, support tickets, or Git/)).toBeVisible();
    expect(screen.getByText(/hostname edge-01/)).toBeVisible();
  });
});
