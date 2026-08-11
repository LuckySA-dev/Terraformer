import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { AppShell } from '../src/components/AppShell';
import type { Device, HealthResponse } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    devices: vi.fn(),
    credentialProfiles: vi.fn(),
    facts: vi.fn(),
    interfaces: vi.fn(),
    neighbors: vi.fn(),
    snapshots: vi.fn(),
    events: vi.fn(),
  },
}));

const mockDeviceId = vi.hoisted(() => '2ad0db14-5a87-4147-a4e7-c98f88322464');

// AppShell's own routing logic (which device stays focused across a Topology
// -> Inventory hand-off) is what's under test here, not TopologyPage's graph
// rendering — that's already covered in topology-page.test.tsx.
vi.mock('../src/features/topology/TopologyPage', () => ({
  default: ({ onFocusDevice }: { onFocusDevice?: (deviceId: string) => void }) => (
    <button type="button" onClick={() => onFocusDevice?.(mockDeviceId)}>
      Focus mock device
    </button>
  ),
}));

const device: Device = {
  id: mockDeviceId,
  name: 'Edge router',
  management_address: '192.0.2.10',
  port: 22,
  vendor: 'cisco_iosxe',
  credential_profile_id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
  ssh_compatibility: 'modern',
  is_lab: false,
  console_transport: 'ssh',
  status: 'reachable',
  facts: { hostname: 'edge-01' },
  capabilities: [],
  last_seen_at: '2026-07-12T01:00:00Z',
  last_error_code: null,
  created_at: '2026-07-12T01:00:00Z',
  updated_at: '2026-07-12T01:00:00Z',
};

const health: HealthResponse = {
  status: 'ok',
  version: '0.1.0',
  checks: {
    database: { status: 'ok' },
    redis: { status: 'ok' },
    worker: { status: 'ok' },
  },
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderShell() {
  return render(<AppShell health={health} onLogout={vi.fn()} />, { wrapper: TestProviders });
}

describe('AppShell sidebar collapse', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api.devices).mockResolvedValue([]);
    vi.mocked(api.credentialProfiles).mockResolvedValue([]);
  });

  it('starts expanded and toggles to collapsed on click, persisting the choice', async () => {
    const user = userEvent.setup();
    const { container } = renderShell();

    expect(container.querySelector('.app-shell')).not.toHaveClass('app-shell--sidebar-collapsed');
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }));

    expect(container.querySelector('.app-shell')).toHaveClass('app-shell--sidebar-collapsed');
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeVisible();
    expect(localStorage.getItem('terraformer.sidebar.collapsed')).toBe('1');

    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }));

    expect(container.querySelector('.app-shell')).not.toHaveClass('app-shell--sidebar-collapsed');
    expect(localStorage.getItem('terraformer.sidebar.collapsed')).toBe('0');
  });

  it('starts collapsed when a previous session left it collapsed', () => {
    localStorage.setItem('terraformer.sidebar.collapsed', '1');
    const { container } = renderShell();

    expect(container.querySelector('.app-shell')).toHaveClass('app-shell--sidebar-collapsed');
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeVisible();
  });
});

describe('AppShell topology device hand-off', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.credentialProfiles).mockResolvedValue([]);
    vi.mocked(api.facts).mockResolvedValue({ device_id: device.id, facts: device.facts, last_seen_at: null });
    vi.mocked(api.interfaces).mockResolvedValue([]);
    vi.mocked(api.neighbors).mockResolvedValue([]);
    vi.mocked(api.snapshots).mockResolvedValue([]);
    vi.mocked(api.events).mockResolvedValue([]);
  });

  it('pre-selects the device focused from Topology, then forgets it on a plain nav click', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole('button', { name: 'Topology' }));
    await user.click(await screen.findByRole('button', { name: 'Focus mock device' }));

    expect(await screen.findByRole('complementary', { name: 'Edge router inspector' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: 'Topology' }));
    await user.click(screen.getByRole('button', { name: 'Device inventory' }));

    expect(screen.queryByRole('complementary', { name: 'Edge router inspector' })).not.toBeInTheDocument();
  });
});
