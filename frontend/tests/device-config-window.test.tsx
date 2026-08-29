import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { DeviceConfigWindow } from '../src/features/config/DeviceConfigWindow';
import { CONFIG_ENTRIES } from '../src/features/config/configCatalog';
import type { ChangePlan, Device, Job } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    interfaces: vi.fn(),
    previewChange: vi.fn(),
    applyChangePlan: vi.fn(),
    listChangePlans: vi.fn(),
    saveRunningConfig: vi.fn(),
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

const queuedJob: Job = {
  id: '4f2e1d0c-9b8a-4756-a3e2-1d0c9b8a7564',
  type: 'apply_change',
  state: 'queued',
  device_id: device.id,
  result: null,
  error_code: null,
  error_message: null,
  created_at: '2026-08-27T01:00:00Z',
  updated_at: '2026-08-27T01:00:00Z',
  started_at: null,
  finished_at: null,
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

/**
 * The window submits straight to the device by default. Tests about staging a
 * plan pick the other mode first, which is the one that still shows a plan and
 * waits for a second click.
 */
const reviewFirst = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole('button', { name: /Review first/ }));

describe('Packet Tracer-style device config window', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listChangePlans).mockResolvedValue([]);
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
    await reviewFirst(user);

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

  it('sends the change on one click, without a plan to accept first', async () => {
    const user = userEvent.setup();
    vi.mocked(api.previewChange).mockResolvedValue(plan);
    vi.mocked(api.applyChangePlan).mockResolvedValue(queuedJob);
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Interfaces/ }));
    await user.click(await screen.findByRole('button', { name: /Edit/ }));
    await user.type(screen.getByLabelText('Description'), 'uplink-to-lab-core');
    // One button, and it says what it does. Preview still runs -- it is what
    // renders the commands and the inverse -- but it is no longer a stop.
    await user.click(at(screen.getAllByRole('button', { name: /Apply/ }), 0));

    await waitFor(() => expect(api.applyChangePlan).toHaveBeenCalledWith(plan.id));
  });

  it('reports what the device did with the change, not just that it was queued', async () => {
    const user = userEvent.setup();
    vi.mocked(api.previewChange).mockResolvedValue(plan);
    vi.mocked(api.applyChangePlan).mockResolvedValue(queuedJob);
    // Apply is queued to the worker, so the status arrives on a later read.
    vi.mocked(api.listChangePlans).mockResolvedValue([{ ...plan, status: 'applied' }]);
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Hostname/ }));
    await user.type(screen.getByLabelText('Hostname'), 'SW2-ACCESS');
    await user.click(screen.getByRole('button', { name: /Apply/ }));

    expect(await screen.findByText(/post-check read the new value back/)).toBeVisible();
    expect(await screen.findByText('ON THE DEVICE')).toBeVisible();
  });

  it('says so plainly when the rollback failed too', async () => {
    const user = userEvent.setup();
    vi.mocked(api.previewChange).mockResolvedValue(plan);
    vi.mocked(api.applyChangePlan).mockResolvedValue(queuedJob);
    vi.mocked(api.listChangePlans).mockResolvedValue([
      { ...plan, status: 'rollback_failed', failure_code: 'post_check_failed' },
    ]);
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Hostname/ }));
    await user.type(screen.getByLabelText('Hostname'), 'SW2-ACCESS');
    await user.click(screen.getByRole('button', { name: /Apply/ }));

    // The one outcome the operator must not miss.
    expect(await screen.findByText(/unknown state/)).toBeVisible();
    expect(await screen.findByText('post_check_failed')).toBeVisible();
    expect(screen.getByText('FAILED')).toBeVisible();
  });

  it('stages a trunk allowed-VLAN list against the port it names', async () => {
    const user = userEvent.setup();
    vi.mocked(api.previewChange).mockResolvedValue(plan);
    vi.mocked(api.applyChangePlan).mockResolvedValue(queuedJob);
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Trunk \/ allowed VLANs/ }));
    await user.selectOptions(await screen.findByLabelText('Interface'), 'GigabitEthernet0/1');
    await user.type(screen.getByLabelText('Allowed VLANs'), '1,10,20-30');
    await user.click(screen.getByRole('button', { name: /Apply/ }));

    await waitFor(() =>
      expect(api.previewChange).toHaveBeenCalledWith({
        device_id: device.id,
        change_type: 'interface_trunk_vlans',
        target: 'GigabitEthernet0/1',
        desired_value: '1,10,20-30',
      }),
    );
  });

  it('warns that the allowed list replaces rather than adds', async () => {
    const user = userEvent.setup();
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Trunk \/ allowed VLANs/ }));
    // Getting this wrong silently drops every VLAN the operator left out of a
    // link that is carrying them, so the form has to say it before they type.
    expect(await screen.findByText(/Replaces the whole list/)).toBeVisible();
  });

  it('stages a static route from a prefix and a next hop', async () => {
    const user = userEvent.setup();
    vi.mocked(api.previewChange).mockResolvedValue(plan);
    vi.mocked(api.applyChangePlan).mockResolvedValue(queuedJob);
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Static route/ }));
    // A route targets a prefix, not a port, so it must not ask for one.
    expect(screen.queryByLabelText('Interface')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Destination prefix'), '10.10.0.0/16');
    await user.type(screen.getByLabelText('Next hop'), '192.0.2.1');
    await user.click(screen.getByRole('button', { name: /Apply/ }));

    await waitFor(() =>
      expect(api.previewChange).toHaveBeenCalledWith({
        device_id: device.id,
        change_type: 'static_route',
        target: '10.10.0.0/16',
        desired_value: '192.0.2.1',
      }),
    );
  });

  it('says the prefix length is required before the operator omits it', async () => {
    const user = userEvent.setup();
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Static route/ }));
    // A bare 10.10.0.0 is a valid /32, so leaving it out routes a different
    // prefix than the operator meant with no error to show for it.
    expect(await screen.findByText(/prefix length is required/)).toBeVisible();
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
      expect(screen.queryByRole('button', { name: /^(Apply|Preview)/ })).not.toBeInTheDocument();
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
    await reviewFirst(user);

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
    vi.mocked(api.listChangePlans).mockResolvedValue([]);
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
    await reviewFirst(user);
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
    vi.mocked(api.listChangePlans).mockResolvedValue([]);
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
    await reviewFirst(user);

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

  it('saves the running-config as its own action, with no plan to preview', async () => {
    const user = userEvent.setup();
    vi.mocked(api.saveRunningConfig).mockResolvedValue({ device_id: device.id, saved: true });
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Save running-config/ }));

    // It has no inverse, so it must not pretend to be a reviewable plan.
    expect(await screen.findByText(/nothing to roll back/)).toBeVisible();
    expect(screen.queryByRole('button', { name: /^(Apply|Preview)/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Write to startup-config/ }));
    await waitFor(() => expect(api.saveRunningConfig).toHaveBeenCalledWith(device.id));
    expect(api.previewChange).not.toHaveBeenCalled();
    expect(await screen.findByText('The device confirmed the save.')).toBeVisible();
  });

  it('reports a save the device did not confirm instead of showing success', async () => {
    const user = userEvent.setup();
    vi.mocked(api.saveRunningConfig).mockRejectedValue(
      new Error('The device did not confirm the save'),
    );
    renderWindow();

    await user.click(screen.getByRole('button', { name: /Save running-config/ }));
    await user.click(screen.getByRole('button', { name: /Write to startup-config/ }));

    // Believing a silent failure is exactly the outcome that matters here:
    // the operator would think the config survives a reload.
    expect(await screen.findByRole('alert')).toHaveTextContent('did not confirm');
    expect(screen.queryByText('The device confirmed the save.')).not.toBeInTheDocument();
  });
});
