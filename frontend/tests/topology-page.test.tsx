import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { TopologyPage } from '../src/features/topology/TopologyPage';
import {
  buildTopologyElements,
  loadManualTopologyLinks,
  TOPOLOGY_MANUAL_LINKS_KEY,
  loadTopologyPositions,
  TOPOLOGY_POSITIONS_KEY,
} from '../src/features/topology/topology';
import type { Device, DeviceNeighbor } from '../src/types/api';

const graph = vi.hoisted(() => ({
  create: vi.fn(),
  destroy: vi.fn(),
  nodes: vi.fn(() => []),
  on: vi.fn(),
}));

vi.mock('cytoscape', () => ({ default: graph.create }));
vi.mock('../src/api/network', () => ({
  api: {
    devices: vi.fn(),
    neighbors: vi.fn(),
  },
}));

const device: Device = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Edge router',
  management_address: '192.0.2.10',
  port: 22,
  vendor: 'cisco_iosxe',
  credential_profile_id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
  status: 'reachable',
  facts: { hostname: 'edge-01' },
  capabilities: [],
  last_seen_at: '2026-07-12T01:00:00Z',
  last_error_code: null,
  created_at: '2026-07-12T01:00:00Z',
  updated_at: '2026-07-12T01:00:00Z',
};

const neighbor: DeviceNeighbor = {
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
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('TopologyPage read-only projection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    graph.create.mockReturnValue({
      destroy: graph.destroy,
      nodes: graph.nodes,
      on: graph.on,
    });
  });

  it('projects registered devices and observed neighbors without adding inventory', () => {
    const elements = buildTopologyElements(
      [device],
      [{ deviceId: device.id, neighbors: [neighbor] }],
    );

    expect(elements).toHaveLength(3);
    const observed = elements.find(
      (element) => element.group === 'nodes' && element.data.kind === 'observed',
    );
    const link = elements.find((element) => element.group === 'edges');
    expect(observed?.data.label).toBe(neighbor.remote_device_name);
    expect(link?.data.protocol).toBe('cdp');
    expect(link?.data.label).toBe('CDP · GigabitEthernet1 → GigabitEthernet0/1');
  });

  it('renders saved neighbor evidence as a graph', async () => {
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockResolvedValue([neighbor]);
    render(<TopologyPage />, { wrapper: TestProviders });

    expect(await screen.findByRole('heading', { name: 'Network topology' })).toBeVisible();
    expect(screen.getByText('2 nodes / 1 links')).toBeVisible();
    expect(screen.getByText(/Observed nodes remain evidence, not inventory records/)).toBeVisible();
    expect(api.neighbors).toHaveBeenCalledWith(device.id);
    expect(graph.create).toHaveBeenCalledOnce();
  });

  it('renders a retryable neighbor API error', async () => {
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockRejectedValue(new Error('Neighbor records unavailable'));
    render(<TopologyPage />, { wrapper: TestProviders });

    expect(await screen.findByText('Neighbor records unavailable')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible();
    expect(graph.create).not.toHaveBeenCalled();
  });

  it('renders an empty state without requesting neighbor APIs', async () => {
    vi.mocked(api.devices).mockResolvedValue([]);
    render(<TopologyPage />, { wrapper: TestProviders });

    expect(await screen.findByRole('heading', { name: 'No topology yet' })).toBeVisible();
    expect(api.neighbors).not.toHaveBeenCalled();
    expect(graph.create).not.toHaveBeenCalled();
  });

  it('loads only finite saved node positions', () => {
    localStorage.setItem(
      TOPOLOGY_POSITIONS_KEY,
      JSON.stringify({
        [`device:${device.id}`]: { x: 10, y: 20 },
        invalid: { x: 'not-a-number', y: 1 },
      }),
    );

    const positions = loadTopologyPositions(localStorage);
    const elements = buildTopologyElements([device], [], positions);

    expect(positions).toEqual({ [`device:${device.id}`]: { x: 10, y: 20 } });
    expect(elements[0]).toMatchObject({ position: { x: 10, y: 20 } });
  });

  it('loads valid browser-local manual links and labels them unverified', () => {
    const second = { ...device, id: '5f7837b9-4bf2-49ab-8205-c9acbf15a31d', name: 'Core' };
    const manual = {
      id: 'local-link-1',
      sourceDeviceId: device.id,
      targetDeviceId: second.id,
    };
    localStorage.setItem(TOPOLOGY_MANUAL_LINKS_KEY, JSON.stringify([manual, null]));

    const links = loadManualTopologyLinks(localStorage);
    const elements = buildTopologyElements([device, second], [], {}, links);
    const edge = elements.find((element) => element.group === 'edges');

    expect(links).toEqual([manual]);
    expect(edge?.data).toMatchObject({ label: 'UNVERIFIED', protocol: 'manual' });
  });
});
