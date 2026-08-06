import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { DeviceInspector } from '../src/features/inventory/DeviceInspector';
import type { ConfigSnapshot, Device, Job } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    facts: vi.fn(),
    interfaces: vi.fn(),
    neighbors: vi.fn(),
    snapshots: vi.fn(),
    snapshot: vi.fn(),
    events: vi.fn(),
    testDeviceConnection: vi.fn(),
    refreshDevice: vi.fn(),
    captureSnapshot: vi.fn(),
    runDiagnostic: vi.fn(),
    job: vi.fn(),
  },
}));

vi.mock('@xterm/xterm', () => ({ Terminal: vi.fn() }));

const device: Device = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Generic edge',
  management_address: '192.0.2.20',
  port: 22,
  vendor: 'generic',
  credential_profile_id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
  ssh_compatibility: 'modern',
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

const queuedDiagnostic: Job = {
  id: '4530ef90-e648-4cb6-b72a-14665d0ce350',
  type: 'run_diagnostic',
  state: 'queued',
  device_id: device.id,
  result: null,
  error_code: null,
  error_message: null,
  created_at: '2026-07-12T02:00:00Z',
  updated_at: '2026-07-12T02:00:00Z',
  started_at: null,
  finished_at: null,
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderInspector(target = device) {
  render(
    <DeviceInspector device={target} onClose={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} />,
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
    vi.mocked(api.neighbors).mockResolvedValue([]);
    vi.mocked(api.snapshots).mockResolvedValue([]);
    vi.mocked(api.events).mockResolvedValue([]);
  });

  it('renders raw observed uptime, capability arrays, and honest Generic driver scope', async () => {
    renderInspector();

    expect(await screen.findByText('9 days, 04:12:11')).toBeVisible();
    expect(screen.getByText('Generic · connection test only')).toBeVisible();
    expect(screen.getByText('Available · Level D')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Configuration is unavailable' })).toBeVisible();
    expect(screen.queryByText('LEGACY SSH')).not.toBeInTheDocument();
  });

  it('labels only saved legacy devices', async () => {
    renderInspector({ ...device, ssh_compatibility: 'cisco_legacy' });

    expect(await screen.findByText('LEGACY SSH')).toBeVisible();
  });

  it('passes saved Group1 mode to the terminal acknowledgment boundary', async () => {
    const user = userEvent.setup();
    renderInspector({ ...device, ssh_compatibility: 'cisco_legacy_group1' });

    await user.click(screen.getByRole('button', { name: 'Terminal' }));

    expect(await screen.findByRole('checkbox', { name: /Group1.*last-resort/ })).not.toBeChecked();
    expect(screen.getByRole('button', { name: /open Direct Mode/ })).toBeDisabled();
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

  it('labels CDP and LLDP records as observed neighbor evidence', async () => {
    const user = userEvent.setup();
    vi.mocked(api.neighbors).mockResolvedValue([
      {
        id: '641d8b94-79a5-469a-ab6d-7793e331f93c',
        device_id: device.id,
        protocol: 'cdp',
        local_interface: 'GigabitEthernet1',
        remote_device_name: 'dist-sw-01.example.test',
        remote_interface: 'GigabitEthernet0/1',
        management_address: '198.51.100.2',
        platform: 'cisco C9300-24T',
        created_at: '2026-07-12T01:00:00Z',
        updated_at: '2026-07-12T01:00:00Z',
      },
    ]);
    renderInspector();

    await user.click(screen.getByRole('button', { name: 'Neighbors' }));

    expect(await screen.findByText('dist-sw-01.example.test')).toBeVisible();
    expect(screen.getByText('CDP · OBSERVED')).toBeVisible();
    expect(screen.getByText('198.51.100.2')).toBeVisible();
  });

  it('renders a retryable neighbor error state', async () => {
    const user = userEvent.setup();
    vi.mocked(api.neighbors).mockRejectedValue(new Error('Neighbor read unavailable'));
    renderInspector();

    await user.click(screen.getByRole('button', { name: 'Neighbors' }));

    expect(await screen.findByText('Neighbor read unavailable')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible();
  });

  it('runs an allowlisted diagnostic and renders sanitized output', async () => {
    const user = userEvent.setup();
    const ciscoDevice: Device = {
      ...device,
      vendor: 'cisco_iosxe',
      capabilities: [
        { name: 'routing', supported: true, safety_level: 'D' },
        { name: 'arp', supported: true, safety_level: 'D' },
        { name: 'mac', supported: true, safety_level: 'D' },
      ],
    };
    vi.mocked(api.runDiagnostic).mockResolvedValue(queuedDiagnostic);
    vi.mocked(api.job).mockResolvedValue({
      ...queuedDiagnostic,
      state: 'succeeded',
      result: {
        device_id: device.id,
        action: 'routing_table',
        output: 'C 192.0.2.0/24 is directly connected',
        truncated: false,
      },
    });
    render(
      <DeviceInspector
        device={ciscoDevice}
        onClose={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
      { wrapper: TestProviders },
    );

    await user.click(screen.getByRole('button', { name: 'Diagnostics' }));
    await user.click(screen.getByRole('button', { name: 'Run read-only diagnostic' }));

    expect(api.runDiagnostic).toHaveBeenCalledWith(device.id, 'routing_table', undefined);
    expect(await screen.findByText(/C 192\.0\.2\.0\/24/)).toBeVisible();
    expect(screen.getByText('SANITIZED')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Download sanitized output' })).toBeVisible();
  });

  it('fails closed when the driver has no diagnostic capability', async () => {
    const user = userEvent.setup();
    renderInspector();

    await user.click(screen.getByRole('button', { name: 'Diagnostics' }));

    expect(await screen.findByRole('heading', { name: 'Diagnostics unavailable' })).toBeVisible();
    expect(api.runDiagnostic).not.toHaveBeenCalled();
  });

  it('requires one exact target for ping', async () => {
    const user = userEvent.setup();
    const ciscoDevice: Device = {
      ...device,
      vendor: 'cisco_iosxe',
      capabilities: [{ name: 'ping', supported: true, safety_level: 'D' }],
    };
    vi.mocked(api.runDiagnostic).mockResolvedValue(queuedDiagnostic);
    render(
      <DeviceInspector
        device={ciscoDevice}
        onClose={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
      { wrapper: TestProviders },
    );

    await user.click(screen.getByRole('button', { name: 'Diagnostics' }));
    const run = screen.getByRole('button', { name: 'Run read-only diagnostic' });
    expect(run).toBeDisabled();
    await user.type(screen.getByRole('textbox', { name: 'Exact IPv4 target' }), '198.51.100.10');
    await user.click(run);

    expect(api.runDiagnostic).toHaveBeenCalledWith(device.id, 'ping', '198.51.100.10');
  });
});
