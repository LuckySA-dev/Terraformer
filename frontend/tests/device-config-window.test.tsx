import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { DeviceConfigWindow } from '../src/features/config/DeviceConfigWindow';
import { CONFIG_ENTRIES } from '../src/features/config/configCatalog';
import type { ChangePlan, Device } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    interfaces: vi.fn(),
    previewChange: vi.fn(),
    applyChangePlan: vi.fn(),
  },
}));

const device: Device = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'SW3',
  management_address: '192.0.2.65',
  port: 22,
  vendor: 'cisco_iosxe',
  is_lab: false,
  console_transport: 'ssh',
  credential_profile_id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
  status: 'reachable',
  facts: { hostname: 'sw3' },
  capabilities: [{ name: 'apply', supported: true, safety_level: 'C' }],
  last_seen_at: '2026-08-27T01:00:00Z',
  last_error_code: null,
  created_at: '2026-08-27T01:00:00Z',
  updated_at: '2026-08-27T01:00:00Z',
};

const plan: ChangePlan = {
  id: '7c1a5f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b',
  device_id: device.id,
  status: 'draft',
  safety_level: 'C',
  risk: 'low',
  source: 'manual',
  failure_code: null,
  applied_at: null,
  steps: [
    {
      id: 'b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e',
      change_type: 'interface_description',
      target: 'GigabitEthernet0/1',
      previous_value: null,
      desired_value: 'uplink-to-lab-core',
      rendered_commands: 'interface GigabitEthernet0/1\ndescription uplink-to-lab-core',
      inverse_commands: 'interface GigabitEthernet0/1\nno description',
    },
  ],
  created_at: '2026-08-27T01:00:00Z',
  updated_at: '2026-08-27T01:00:00Z',
};

/** Indexing helper: the project forbids non-null assertions in source. */
function at<T>(items: readonly T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`expected an element at index ${String(index)}`);
  return item;
}

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const renderWindow = () =>
  render(<DeviceConfigWindow device={device} onClose={vi.fn()} />, { wrapper: TestProviders });

describe('Packet Tracer-style device config window', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.interfaces).mockResolvedValue([
      {
        id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        device_id: device.id,
        name: 'GigabitEthernet0/1',
        description: null,
        admin_up: true,
        oper_up: true,
        mac_address: null,
        speed_mbps: null,
        ipv4_addresses: [],
        created_at: '2026-08-27T01:00:00Z',
        updated_at: '2026-08-27T01:00:00Z',
      },
    ]);
  });

  it('previews a change and shows the exact commands it would send', async () => {
    const user = userEvent.setup();
    vi.mocked(api.previewChange).mockResolvedValue(plan);
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Interfaces/ }));
    // The port is picked from the table rather than a dropdown, and the form
    // opens on what the device reported.
    await user.click(await screen.findByRole('button', { name: /Edit/ }));
    await user.type(screen.getByLabelText('Description'), 'uplink-to-lab-core');
    await user.click(at(screen.getAllByRole('button', { name: /Preview/ }), 0));

    // Packet Tracer's "Equivalent IOS Commands" pane, but for a real device --
    // so it must be explicit that nothing has been sent yet.
    const pane = await screen.findByLabelText('Equivalent IOS commands');
    expect(pane).toHaveTextContent('description uplink-to-lab-core');
    expect(screen.getByText('NOT YET SENT')).toBeVisible();
    // The rollback commands are shown nowhere else in the UI.
    expect(screen.getByLabelText('Rollback commands')).toHaveTextContent('no description');
    expect(api.applyChangePlan).not.toHaveBeenCalled();
  });

  it('offers no way to send a capability that is not implemented', async () => {
    const user = userEvent.setup();
    renderWindow();

    // Every unbuilt entry is listed so the operator can see where a capability
    // will land, but docs/safety-model.md forbids exposing a control that
    // could execute one. Selecting each must yield a reason and no form.
    for (const entry of CONFIG_ENTRIES.filter((item) => !item.available)) {
      await user.click(screen.getByRole('button', { name: new RegExp(entry.label) }));
      expect(await screen.findByText(`${entry.label} is not available yet`)).toBeVisible();
      expect(screen.queryByRole('button', { name: /Preview/ })).not.toBeInTheDocument();
    }
    expect(api.previewChange).not.toHaveBeenCalled();
    expect(api.applyChangePlan).not.toHaveBeenCalled();
  });

  it('closes from the title bar even though the bar is also the drag handle', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<DeviceConfigWindow device={device} onClose={onClose} />, { wrapper: TestProviders });

    // Capturing the pointer for the drag used to retarget the whole gesture to
    // the bar, so the close button never received its click.
    await user.click(screen.getByRole('button', { name: 'Close configuration window' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('lists the routing protocols the operator asked for as declared, not offered', () => {
    renderWindow();
    for (const label of ['Static route', 'RIP v1 / v2', 'EIGRP', 'OSPF', 'BGP']) {
      expect(screen.getByRole('button', { name: new RegExp(label) })).toBeVisible();
    }
  });

  it('drops a staged plan when the operator switches category', async () => {
    const user = userEvent.setup();
    vi.mocked(api.previewChange).mockResolvedValue(plan);
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Interfaces/ }));
    await user.click(await screen.findByRole('button', { name: /Edit/ }));
    await user.type(screen.getByLabelText('Description'), 'uplink');
    await user.click(at(screen.getAllByRole('button', { name: /Preview/ }), 0));
    expect(await screen.findByLabelText('Equivalent IOS commands'))
      .toHaveTextContent('description uplink-to-lab-core');

    // A plan describes one specific change; leaving it on screen under a
    // different category would invite applying it believing it was the new one.
    await user.click(screen.getByRole('button', { name: /VLAN database/ }));
    expect(screen.getByLabelText('Equivalent IOS commands'))
      .not.toHaveTextContent('description uplink-to-lab-core');
    expect(screen.queryByLabelText('Rollback commands')).not.toBeInTheDocument();
    expect(screen.getByText('NOTHING STAGED')).toBeVisible();
  });
});

describe('Interface table', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.interfaces).mockResolvedValue([
      {
        id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d',
        device_id: device.id,
        name: 'GigabitEthernet0/1',
        description: 'to-core',
        admin_up: true,
        oper_up: true,
        mac_address: null,
        speed_mbps: 1000,
        ipv4_addresses: ['192.0.2.65/24'],
        created_at: '2026-08-27T01:00:00Z',
        updated_at: '2026-08-27T01:00:00Z',
      },
      {
        id: 'b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6f',
        device_id: device.id,
        name: 'GigabitEthernet0/2',
        description: null,
        admin_up: false,
        oper_up: false,
        mac_address: null,
        speed_mbps: null,
        ipv4_addresses: [],
        created_at: '2026-08-27T01:00:00Z',
        updated_at: '2026-08-27T01:00:00Z',
      },
    ]);
  });

  const openTable = async (user: ReturnType<typeof userEvent.setup>) => {
    renderWindow();
    await user.click(screen.getByRole('button', { name: /Interfaces/ }));
    return screen.findAllByRole('button', { name: /Edit/ });
  };

  it('lists every interface with its observed state', async () => {
    const user = userEvent.setup();
    await openTable(user);

    expect(screen.getByText('GigabitEthernet0/1')).toBeVisible();
    expect(screen.getByText('GigabitEthernet0/2')).toBeVisible();
    expect(screen.getByText('to-core')).toBeVisible();
    expect(screen.getByText('192.0.2.65/24')).toBeVisible();
  });

  it('opens the editor on the values the device reported', async () => {
    const user = userEvent.setup();
    const edits = await openTable(user);
    await user.click(at(edits, 0));

    // The whole point: changing one field is an edit, not a re-entry.
    expect(screen.getByLabelText('Description')).toHaveValue('to-core');
    expect(screen.getByLabelText('Port status')).toHaveValue('up');
  });

  it('will not preview a field the operator has not actually changed', async () => {
    const user = userEvent.setup();
    const edits = await openTable(user);
    await user.click(at(edits, 0));

    const previews = screen.getAllByRole('button', { name: /Preview/ });
    // Description and port status still match the device, so staging them
    // would send a change that changes nothing.
    expect(previews[0]).toBeDisabled();
    expect(previews[1]).toBeDisabled();

    await user.clear(screen.getByLabelText('Description'));
    await user.type(screen.getByLabelText('Description'), 'to-access');
    expect(at(screen.getAllByRole('button', { name: /Preview/ }), 0)).toBeEnabled();
  });

  it('stages the edited port, not the first one in the list', async () => {
    const user = userEvent.setup();
    vi.mocked(api.previewChange).mockResolvedValue(plan);
    const edits = await openTable(user);
    await user.click(at(edits, 1));

    await user.selectOptions(screen.getByLabelText('Port status'), 'up');
    await user.click(at(screen.getAllByRole('button', { name: /Preview/ }), 1));

    await waitFor(() =>
      expect(api.previewChange).toHaveBeenCalledWith({
        device_id: device.id,
        change_type: 'interface_admin_state',
        target: 'GigabitEthernet0/2',
        desired_value: 'up',
      }),
    );
  });

  it('shows the address as read-only rather than pretending it can be changed', async () => {
    const user = userEvent.setup();
    const edits = await openTable(user);
    await user.click(at(edits, 0));

    expect(screen.getByText('IPv4 address')).toBeVisible();
    // docs/CAPABILITY_MATRIX.md has this as Not Implemented, so there must be
    // no input bound to it.
    expect(screen.queryByLabelText('IPv4 address')).not.toBeInTheDocument();
  });
});

describe('Global configuration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.interfaces).mockResolvedValue([]);
  });

  it('renames the device without asking for a target to pick', async () => {
    const user = userEvent.setup();
    vi.mocked(api.previewChange).mockResolvedValue({
      ...plan,
      steps: [{
        ...at(plan.steps, 0),
        change_type: 'hostname',
        target: '',
        desired_value: 'SW2-ACCESS',
        rendered_commands: 'hostname SW2-ACCESS',
        inverse_commands: 'hostname SW2',
      }],
    });
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Hostname/ }));
    // A global change targets the device, so there is no interface or VLAN
    // field to fill in first.
    expect(screen.queryByLabelText('Interface')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('VLAN id')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Hostname'), 'SW2-ACCESS');
    await user.click(screen.getByRole('button', { name: /Preview/ }));

    await waitFor(() =>
      expect(api.previewChange).toHaveBeenCalledWith({
        device_id: device.id,
        change_type: 'hostname',
        target: '',
        desired_value: 'SW2-ACCESS',
      }),
    );
    expect(await screen.findByLabelText('Rollback commands')).toHaveTextContent('hostname SW2');
  });

  it('keeps saving the running-config declared rather than offered', async () => {
    const user = userEvent.setup();
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Save running-config/ }));

    // It is the one entry with no inverse, so it cannot go through a pipeline
    // whose safety story is "we can put it back".
    expect(await screen.findByText(/no inverse/)).toBeVisible();
    expect(screen.queryByRole('button', { name: /Preview/ })).not.toBeInTheDocument();
  });
});
