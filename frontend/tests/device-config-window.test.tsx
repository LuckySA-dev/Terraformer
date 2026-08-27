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

    await user.click(screen.getByRole('button', { name: /Description/ }));
    await waitFor(() => expect(screen.getByLabelText('Interface')).toBeVisible());
    await user.selectOptions(screen.getByLabelText('Interface'), 'GigabitEthernet0/1');
    await user.type(screen.getByLabelText('Description'), 'uplink-to-lab-core');
    await user.click(screen.getByRole('button', { name: /Preview/ }));

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

    await user.click(screen.getByRole('button', { name: /Description/ }));
    await waitFor(() => expect(screen.getByLabelText('Interface')).toBeVisible());
    await user.selectOptions(screen.getByLabelText('Interface'), 'GigabitEthernet0/1');
    await user.type(screen.getByLabelText('Description'), 'uplink');
    await user.click(screen.getByRole('button', { name: /Preview/ }));
    expect(await screen.findByLabelText('Equivalent IOS commands'))
      .toHaveTextContent('description uplink-to-lab-core');

    // A plan describes one specific change; leaving it on screen under a
    // different category would invite applying it believing it was the new one.
    await user.click(screen.getByRole('button', { name: /Port status/ }));
    expect(screen.getByLabelText('Equivalent IOS commands'))
      .not.toHaveTextContent('description uplink-to-lab-core');
    expect(screen.queryByLabelText('Rollback commands')).not.toBeInTheDocument();
    expect(screen.getByText('NOTHING STAGED')).toBeVisible();
  });
});
