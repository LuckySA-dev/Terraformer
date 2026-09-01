import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { TopologyPage } from '../src/features/topology/TopologyPage';
import {
  abbreviateInterface,
  buildTopologyElements,
  loadManualTopologyLinks,
  TOPOLOGY_MANUAL_LINKS_KEY,
  loadTopologyPositions,
  shortenDeviceLabel,
  TOPOLOGY_POSITIONS_KEY,
} from '../src/features/topology/topology';
import type { Device, DeviceNeighbor } from '../src/types/api';

const graph = vi.hoisted(() => {
  // Array-like so the drag handler's .map() works, with the class helpers the
  // selection effect calls on a cytoscape collection.
  const collection = (): unknown =>
    Object.assign([] as unknown[], {
      addClass: vi.fn(),
      removeClass: vi.fn(),
      // Selecting a device also highlights its cables, so the double has to
      // offer the same traversal the real collection does.
      connectedEdges: vi.fn(() => collection()),
    });
  return {
    collection,
    create: vi.fn(),
    destroy: vi.fn(),
    nodes: vi.fn(() => collection()),
    elements: vi.fn(() => collection()),
    getElementById: vi.fn(() => collection()),
    on: vi.fn(),
    one: vi.fn(),
    // The view starts fitted, then the page caps how far `fit` may zoom in so a
    // two-node graph is not magnified to fill the canvas. Default the double
    // above that cap so a test can observe the correction happening.
    zoom: vi.fn(() => 2.5),
    center: vi.fn(),
  };
});

vi.mock('cytoscape', () => ({ default: Object.assign(graph.create, { use: vi.fn() }) }));
vi.mock('../src/api/network', () => ({
  api: {
    devices: vi.fn(),
    neighbors: vi.fn(),
    facts: vi.fn(),
    interfaces: vi.fn(),
    snapshots: vi.fn(),
    events: vi.fn(),
    // The config window polls this for the outcome of an apply.
    listChangePlans: vi.fn(),
  },
}));

const device: Device = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Edge router',
  management_address: '192.0.2.10',
  port: 22,
  vendor: 'cisco_iosxe',
    is_lab: false,
    console_transport: 'ssh',
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

const lldpNeighbor: DeviceNeighbor = {
  id: '9a1f2a3b-4c5d-6e7f-8091-a2b3c4d5e6f7',
  device_id: device.id,
  protocol: 'lldp',
  local_interface: 'GigabitEthernet2',
  remote_device_name: 'core-sw-01.example.test',
  remote_interface: 'GigabitEthernet0/2',
  management_address: '198.51.100.3',
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
    // clearAllMocks drops recorded calls but keeps a mockReturnValue, so a test
    // that swaps `nodes` for a bare array would otherwise strip the collection
    // helpers from every test that ran after it.
    graph.nodes.mockImplementation(() => graph.collection());
    graph.create.mockReturnValue({
      destroy: graph.destroy,
      nodes: graph.nodes,
      elements: graph.elements,
      on: graph.on,
      one: graph.one,
      zoom: graph.zoom,
      center: graph.center,
      getElementById: graph.getElementById,
    });
    vi.mocked(api.facts).mockResolvedValue({ device_id: device.id, facts: device.facts, last_seen_at: null });
    vi.mocked(api.interfaces).mockResolvedValue([]);
    vi.mocked(api.snapshots).mockResolvedValue([]);
    vi.mocked(api.events).mockResolvedValue([]);
    vi.mocked(api.listChangePlans).mockResolvedValue([]);
  });

  const tapNode = (nodeId: string) => {
    const call = graph.on.mock.calls.find((entry) => entry[0] === 'tap' && entry[1] === 'node');
    const handler = call?.[2] as ((event: { target: { id: () => string } }) => void) | undefined;
    act(() => handler?.({ target: { id: () => nodeId } }));
  };

  const dragNode = () => {
    const call = graph.on.mock.calls.find((entry) => entry[0] === 'dragfree' && entry[1] === 'node');
    const handler = call?.[2] as (() => void) | undefined;
    act(() => handler?.());
  };

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
    // FQDN is shortened to the hostname, and interfaces to Cisco short forms,
    // so a dense graph stays readable; protocol is carried by edge colour.
    expect(observed?.data.label).toBe('dist-sw-01');
    expect(link?.data.protocol).toBe('cdp');
    expect(link?.data.label).toBe('Gi1 → Gi0/1');
  });

  it.each([
    ['GigabitEthernet1/0/1', 'Gi1/0/1'],
    ['FastEthernet0/1', 'Fa0/1'],
    ['TenGigabitEthernet1/1/1', 'Te1/1/1'],
    ['Port-channel12', 'Po12'],
    ['Vlan10', 'Vl10'],
    ['unknown-iface0', 'unknown-iface0'],
  ])('abbreviates %s to %s', (full, short) => {
    expect(abbreviateInterface(full)).toBe(short);
  });

  it.each([
    ['sw1.example.test', 'sw1'],
    ['sw1', 'sw1'],
  ])('shortens device label %s to %s', (full, short) => {
    expect(shortenDeviceLabel(full)).toBe(short);
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
    const call = graph.create.mock.calls[0]?.[0] as {
      layout?: { name?: string; nodeDimensionsIncludeLabels?: boolean };
    } | undefined;
    expect(call?.layout?.name).toBe('fcose');
    expect(call?.layout?.nodeDimensionsIncludeLabels).toBe(true);
  });

  it('caps how far the initial fit may zoom a sparse graph in', async () => {
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockResolvedValue([]);
    render(<TopologyPage />, { wrapper: TestProviders });

    expect(await screen.findByRole('heading', { name: 'Network topology' })).toBeVisible();
    // The double reports a fitted zoom of 2.5 -- the ceiling `fit` would reach
    // on a two-node graph, which rendered the glyphs several times their
    // intended size. The page must pull it back and re-centre.
    expect(graph.zoom).toHaveBeenCalledWith(1);
    expect(graph.center).toHaveBeenCalled();
  });

  it('filters out a protocol and its now-orphaned observed node when unchecked', async () => {
    const user = userEvent.setup();
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockResolvedValue([neighbor, lldpNeighbor]);
    render(<TopologyPage />, { wrapper: TestProviders });

    expect(await screen.findByText('3 nodes / 2 links')).toBeVisible();

    await user.click(screen.getByLabelText('LLDP'));

    expect(screen.getByText('2 nodes / 1 links')).toBeVisible();
  });

  it('hides links and nodes touching an unregistered device when Registered only is checked', async () => {
    const user = userEvent.setup();
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockResolvedValue([neighbor, lldpNeighbor]);
    render(<TopologyPage />, { wrapper: TestProviders });

    expect(await screen.findByText('3 nodes / 2 links')).toBeVisible();

    await user.click(screen.getByLabelText('Registered only'));

    expect(screen.getByText('1 nodes / 0 links')).toBeVisible();
  });

  it('opens the Device Inspector for a registered node on tap', async () => {
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockResolvedValue([neighbor]);
    render(<TopologyPage onFocusDevice={vi.fn()} />, { wrapper: TestProviders });
    await screen.findByText('2 nodes / 1 links');

    tapNode(`device:${device.id}`);

    expect(await screen.findByRole('complementary', { name: 'Edge router inspector' })).toBeVisible();
  });

  it('does not rebuild or re-lay-out the graph when a node is tapped', async () => {
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockResolvedValue([neighbor]);
    render(<TopologyPage onFocusDevice={vi.fn()} />, { wrapper: TestProviders });
    await screen.findByText('2 nodes / 1 links');
    expect(graph.create).toHaveBeenCalledOnce();

    tapNode(`device:${device.id}`);
    await screen.findByRole('complementary', { name: 'Edge router inspector' });

    // Selecting a node must not destroy the instance and re-run the layout,
    // which visibly resets the graph the operator is working with.
    expect(graph.create).toHaveBeenCalledOnce();
    expect(graph.destroy).not.toHaveBeenCalled();
  });

  it('does not open the inspector for an observed-only node', async () => {
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockResolvedValue([neighbor]);
    render(<TopologyPage onFocusDevice={vi.fn()} />, { wrapper: TestProviders });
    await screen.findByText('2 nodes / 1 links');

    tapNode(`observed:${neighbor.id}`);

    // With nothing selected the inspector is not rendered at all, so the
    // graph keeps the full width instead of showing an empty side panel.
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
  });

  it('hands editing and deleting off to Inventory instead of doing it inline', async () => {
    const user = userEvent.setup();
    const onFocusDevice = vi.fn();
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockResolvedValue([neighbor]);
    render(<TopologyPage onFocusDevice={onFocusDevice} />, { wrapper: TestProviders });
    await screen.findByText('2 nodes / 1 links');

    tapNode(`device:${device.id}`);
    await screen.findByRole('complementary', { name: 'Edge router inspector' });
    await user.click(screen.getByRole('button', { name: 'Delete device' }));

    expect(onFocusDevice).toHaveBeenCalledWith(device.id);
  });

  it('renders a retryable neighbor API error', async () => {
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors).mockRejectedValue(new Error('Neighbor records unavailable'));
    render(<TopologyPage />, { wrapper: TestProviders });

    expect(await screen.findByText('Neighbor records unavailable')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeVisible();
    expect(graph.create).not.toHaveBeenCalled();
  });

  it('keeps the last observed topology visible when a refresh fails', async () => {
    const user = userEvent.setup();
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.neighbors)
      .mockResolvedValueOnce([neighbor])
      .mockRejectedValueOnce(new Error('Neighbor records unavailable'));
    render(<TopologyPage />, { wrapper: TestProviders });

    expect(await screen.findByRole('img', { name: /read-only topology/i })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Refresh view' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/showing last observed topology/i);
    expect(screen.getByRole('img', { name: /read-only topology/i })).toBeVisible();
  });

  it('renders an empty state without requesting neighbor APIs', async () => {
    vi.mocked(api.devices).mockResolvedValue([]);
    render(<TopologyPage />, { wrapper: TestProviders });

    expect(await screen.findByRole('heading', { name: 'No topology yet' })).toBeVisible();
    expect(api.neighbors).not.toHaveBeenCalled();
    expect(graph.create).not.toHaveBeenCalled();
  });

  it('merges a dragged position instead of overwriting positions of nodes hidden by the current filter', async () => {
    const second = { ...device, id: '5f7837b9-4bf2-49ab-8205-c9acbf15a31d', name: 'Core' };
    localStorage.setItem(
      TOPOLOGY_POSITIONS_KEY,
      JSON.stringify({ [`device:${second.id}`]: { x: 5, y: 5 } }),
    );
    vi.mocked(api.devices).mockResolvedValue([device, second]);
    vi.mocked(api.neighbors).mockResolvedValue([]);
    render(<TopologyPage />, { wrapper: TestProviders });
    await screen.findByText('2 nodes / 0 links');

    // Simulate the graph currently only rendering `device` -- as it would
    // once a filter hides `second` -- then drag the visible node.
    graph.nodes.mockReturnValue([
      { id: () => `device:${device.id}`, position: () => ({ x: 40, y: 60 }) },
    ] as never);
    dragNode();

    const stored = JSON.parse(localStorage.getItem(TOPOLOGY_POSITIONS_KEY) ?? '{}') as Record<string, unknown>;
    expect(stored[`device:${second.id}`]).toEqual({ x: 5, y: 5 });
    expect(stored[`device:${device.id}`]).toEqual({ x: 40, y: 60 });
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

  describe('configuring several devices at once', () => {
    // The shared fixture advertises no capabilities, so its config window would
    // only ever render "no verified apply capability" and never a form.
    const configurable = {
      capabilities: [{ name: 'apply', supported: true, safety_level: 'C' as const }],
    };
    const first: Device = { ...device, ...configurable };
    const second: Device = {
      ...device,
      ...configurable,
      id: '5f7837b9-4bf2-49ab-8205-c9acbf15a31d',
      name: 'SW2',
      management_address: '192.0.2.11',
    };

    /** Fires the node double-tap the page registers on the graph. */
    const openWindowFor = async (deviceId: string) => {
      const registration = graph.on.mock.calls.find(
        (call) => call[0] === 'dbltap' && call[1] === 'node',
      );
      if (registration === undefined) throw new Error('no dbltap handler was registered');
      const handler = registration[2] as (event: unknown) => void;
      await act(async () => {
        handler({ target: { id: () => `device:${deviceId}` } });
        await Promise.resolve();
      });
    };

    const openBoth = async () => {
      vi.mocked(api.devices).mockResolvedValue([first, second]);
      vi.mocked(api.neighbors).mockResolvedValue([]);
      render(<TopologyPage />, { wrapper: TestProviders });
      expect(await screen.findByRole('heading', { name: 'Network topology' })).toBeVisible();
      await openWindowFor(device.id);
      await openWindowFor(second.id);
    };

    it('keeps both windows open rather than replacing the first', async () => {
      await openBoth();
      // Packet Tracer lets several devices be configured side by side, so
      // opening SW2 must not close the window already on the first device.
      expect(
        await screen.findByRole('dialog', { name: `Configure ${device.name}` }),
      ).toBeVisible();
      expect(await screen.findByRole('dialog', { name: 'Configure SW2' })).toBeVisible();
    });

    it('raises the window that was pressed last', async () => {
      await openBoth();
      const first = await screen.findByRole('dialog', { name: `Configure ${device.name}` });
      const latest = await screen.findByRole('dialog', { name: 'Configure SW2' });
      // Opened second, so it starts on top.
      expect(Number(latest.style.zIndex)).toBeGreaterThan(Number(first.style.zIndex));

      await act(async () => {
        fireEvent.pointerDown(first);
        await Promise.resolve();
      });
      expect(Number(first.style.zIndex)).toBeGreaterThan(Number(latest.style.zIndex));
    });

    it('re-opening a device already on screen raises it instead of duplicating it', async () => {
      await openBoth();
      await openWindowFor(device.id);

      expect(screen.getAllByRole('dialog', { name: `Configure ${device.name}` })).toHaveLength(1);
      const first = screen.getByRole('dialog', { name: `Configure ${device.name}` });
      const latest = screen.getByRole('dialog', { name: 'Configure SW2' });
      expect(Number(first.style.zIndex)).toBeGreaterThan(Number(latest.style.zIndex));
    });

    it('keeps each window reading only its own device', async () => {
      await openBoth();

      // Two windows share a query cache. A key that collided would show one
      // device's change history and interfaces under the other's name.
      expect(api.listChangePlans).toHaveBeenCalledWith(device.id);
      expect(api.listChangePlans).toHaveBeenCalledWith(second.id);
      expect(api.interfaces).toHaveBeenCalledWith(device.id);
      expect(api.interfaces).toHaveBeenCalledWith(second.id);
    });

    it('stops opening windows once the cap is reached, dropping the oldest', async () => {
      const many = Array.from({ length: 8 }, (_, index) => ({
        ...device,
        id: `9f1d3a2b-0000-4000-8000-0000000001${String(index).padStart(2, '0')}`,
        name: `SW${String(index)}`,
      }));
      vi.mocked(api.devices).mockResolvedValue(many);
      vi.mocked(api.neighbors).mockResolvedValue([]);
      render(<TopologyPage />, { wrapper: TestProviders });
      expect(await screen.findByRole('heading', { name: 'Network topology' })).toBeVisible();

      for (const item of many) await openWindowFor(item.id);

      // Unbounded, the cascade walks off screen and the stacking order climbs
      // into the layer the menus use.
      const open = screen.getAllByRole('dialog', { name: /^Configure SW/ });
      expect(open).toHaveLength(6);
      // The two least recently opened are the ones gone.
      expect(screen.queryByRole('dialog', { name: 'Configure SW0' })).not.toBeInTheDocument();
      expect(screen.queryByRole('dialog', { name: 'Configure SW1' })).not.toBeInTheDocument();
      expect(screen.getByRole('dialog', { name: 'Configure SW7' })).toBeVisible();
      for (const dialog of open) {
        expect(Number(dialog.style.zIndex)).toBeLessThan(70);
      }
    });

    it('re-focusing an old window saves it from being dropped', async () => {
      const many = Array.from({ length: 6 }, (_, index) => ({
        ...device,
        id: `9f1d3a2b-0000-4000-8000-0000000002${String(index).padStart(2, '0')}`,
        name: `SW${String(index)}`,
      }));
      const extra = { ...device, id: '9f1d3a2b-0000-4000-8000-000000000299', name: 'SW9' };
      vi.mocked(api.devices).mockResolvedValue([...many, extra]);
      vi.mocked(api.neighbors).mockResolvedValue([]);
      render(<TopologyPage />, { wrapper: TestProviders });
      expect(await screen.findByRole('heading', { name: 'Network topology' })).toBeVisible();

      for (const item of many) await openWindowFor(item.id);
      // Touching the oldest makes it the newest, so the next one over the cap
      // takes the window that has actually been idle longest instead.
      await act(async () => {
        fireEvent.pointerDown(screen.getByRole('dialog', { name: 'Configure SW0' }));
        await Promise.resolve();
      });
      await openWindowFor(extra.id);

      expect(screen.getByRole('dialog', { name: 'Configure SW0' })).toBeVisible();
      expect(screen.queryByRole('dialog', { name: 'Configure SW1' })).not.toBeInTheDocument();
    });

    it('keeps what is typed in a window when another one is raised', async () => {
      const user = userEvent.setup();
      await openBoth();

      const first = await screen.findByRole('dialog', { name: `Configure ${device.name}` });
      await user.click(within(first).getByRole('button', { name: /Hostname/ }));
      await user.type(within(first).getByLabelText('Hostname'), 'SW1-CORE');

      // Raising reorders the list, which re-renders every window. Unkeyed,
      // React would match them by position and hand one window's state to
      // another -- the half-typed change would move or vanish.
      const other = screen.getByRole('dialog', { name: 'Configure SW2' });
      await act(async () => {
        fireEvent.pointerDown(other);
        await Promise.resolve();
      });

      const stillFirst = screen.getByRole('dialog', { name: `Configure ${device.name}` });
      expect(within(stillFirst).getByLabelText('Hostname')).toHaveValue('SW1-CORE');
      // SW2 opens on the same entry, so it has a Hostname field of its own --
      // it must be empty. Both windows rendered a field whose id was derived
      // from the label, so the document held two elements with the same id and
      // a label bound to whichever came first.
      expect(within(other).getByLabelText('Hostname')).toHaveValue('');
    });

    it('does not move a window when the stacking order changes', async () => {
      await openBoth();
      const first = await screen.findByRole('dialog', { name: `Configure ${device.name}` });
      const before = { left: first.style.left, top: first.style.top };

      await act(async () => {
        fireEvent.pointerDown(first);
        await Promise.resolve();
      });

      // Windows cascade by their position in the list, so a window that got
      // reordered would jump across the screen under the pointer.
      const after = screen.getByRole('dialog', { name: `Configure ${device.name}` });
      expect({ left: after.style.left, top: after.style.top }).toEqual(before);
    });

    it('closes one window without touching the other', async () => {
      const user = userEvent.setup();
      await openBoth();

      const latest = await screen.findByRole('dialog', { name: 'Configure SW2' });
      await user.click(
        within(latest).getByRole('button', { name: 'Close configuration window' }),
      );

      expect(screen.queryByRole('dialog', { name: 'Configure SW2' })).not.toBeInTheDocument();
      expect(screen.getByRole('dialog', { name: `Configure ${device.name}` })).toBeVisible();
    });
  });
});

it('folds a registered device back in when it advertises a different address', () => {
  // Real lab data: SW3 is reachable on .65 but tells its neighbours .97.
  // Matching on address alone drew it a second time as an observed node.
  const elements = buildTopologyElements(
    [device],
    [{
      deviceId: 'other-device-id',
      neighbors: [{
        ...neighbor,
        remote_device_name: `${device.facts.hostname ?? ""}.cisco`,
        management_address: '192.0.2.199',
      }],
    }],
  );

  const nodes = elements.filter((element) => element.group === 'nodes');
  expect(nodes).toHaveLength(1);
  expect(nodes[0]?.data.kind).toBe('registered');
  const link = elements.find((element) => element.group === 'edges');
  expect(link?.data.target).toBe(`device:${device.id}`);
  expect(link?.data.verified).toBe(true);
});

it('still shows a genuinely unknown neighbour as observed', () => {
  const elements = buildTopologyElements(
    [device],
    [{ deviceId: device.id, neighbors: [{ ...neighbor, remote_device_name: 'DESKTOP-O33JTS7', management_address: null }] }],
  );

  expect(
    elements.filter((element) => element.group === 'nodes' && element.data.kind === 'observed'),
  ).toHaveLength(1);
});
