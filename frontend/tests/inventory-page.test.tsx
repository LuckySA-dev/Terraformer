import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { InventoryPage } from '../src/features/inventory/InventoryPage';
import type { CredentialProfile, Device } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    devices: vi.fn(),
    credentialProfiles: vi.fn(),
    createCredentialProfile: vi.fn(),
    updateCredentialProfile: vi.fn(),
    deleteCredentialProfile: vi.fn(),
    facts: vi.fn(),
    interfaces: vi.fn(),
    neighbors: vi.fn(),
    snapshots: vi.fn(),
    events: vi.fn(),
    testDeviceConnection: vi.fn(),
    refreshDevice: vi.fn(),
  },
}));

const credential: CredentialProfile = {
  id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
  name: 'Lab admin',
  has_username: true,
  has_password: true,
  has_enable_password: true,
  created_at: '2026-07-11T00:00:00Z',
  updated_at: '2026-07-11T00:00:00Z',
};

const device: Device = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Edge router',
  management_address: '192.0.2.10',
  port: 22,
  vendor: 'cisco_iosxe',
  credential_profile_id: credential.id,
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

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderInventory() {
  render(<InventoryPage />, { wrapper: TestProviders });
}

describe('InventoryPage credential profile management', () => {
  beforeEach(() => {
    vi.mocked(api.devices).mockResolvedValue([]);
    vi.mocked(api.credentialProfiles).mockResolvedValue([credential]);
  });

  it('opens a list of saved profiles from the header button', async () => {
    const user = userEvent.setup();
    renderInventory();

    await user.click(screen.getByRole('button', { name: 'Credential profile' }));

    const dialog = await screen.findByRole('dialog', { name: 'Credential profiles' });
    expect(within(dialog).getByText('Lab admin')).toBeVisible();
  });

  it('shows an empty state and offers to create the first profile', async () => {
    vi.mocked(api.credentialProfiles).mockResolvedValue([]);
    const user = userEvent.setup();
    renderInventory();

    await user.click(screen.getByRole('button', { name: 'Credential profile' }));

    expect(await screen.findByText('No credential profiles yet')).toBeVisible();
  });

  it('opens the edit form prefilled from the list, and saves via update', async () => {
    vi.mocked(api.updateCredentialProfile).mockResolvedValue({ ...credential, name: 'Renamed' });
    const user = userEvent.setup();
    renderInventory();

    await user.click(screen.getByRole('button', { name: 'Credential profile' }));
    await user.click(await screen.findByRole('button', { name: 'Edit Lab admin' }));

    expect(await screen.findByRole('dialog', { name: 'Edit credential profile' })).toBeVisible();
    expect(screen.getByLabelText('Profile name')).toHaveValue('Lab admin');

    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(api.updateCredentialProfile).toHaveBeenCalledWith(credential.id, { name: 'Lab admin' });
  });

  it('deletes a profile through a separate confirmation modal', async () => {
    vi.mocked(api.deleteCredentialProfile).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderInventory();

    await user.click(screen.getByRole('button', { name: 'Credential profile' }));
    await user.click(await screen.findByRole('button', { name: 'Delete Lab admin' }));

    const confirm = await screen.findByRole('dialog', { name: 'Remove credential profile?' });
    expect(within(confirm).getByText('Lab admin')).toBeVisible();
    await user.click(within(confirm).getByRole('button', { name: 'Remove profile' }));

    expect(api.deleteCredentialProfile).toHaveBeenCalledWith(credential.id);
  });

  it('still opens the profile-list-independent quick-create shortcut from the device form', async () => {
    const user = userEvent.setup();
    renderInventory();

    await user.click(screen.getByRole('button', { name: 'Add device' }));
    await user.click(await screen.findByRole('button', { name: /new profile/i }));

    expect(await screen.findByRole('dialog', { name: 'New credential profile' })).toBeVisible();
  });
});

describe('InventoryPage device inspector collapse', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(api.devices).mockResolvedValue([device]);
    vi.mocked(api.credentialProfiles).mockResolvedValue([credential]);
    vi.mocked(api.facts).mockResolvedValue({
      device_id: device.id,
      facts: device.facts,
      last_seen_at: device.last_seen_at,
    });
    vi.mocked(api.interfaces).mockResolvedValue([]);
    vi.mocked(api.neighbors).mockResolvedValue([]);
    vi.mocked(api.snapshots).mockResolvedValue([]);
    vi.mocked(api.events).mockResolvedValue([]);
  });

  it('gives the table full width until a device is selected', async () => {
    renderInventory();

    const inspector = await screen.findByRole('complementary', { name: 'Device inspector' });
    expect(inspector.closest('.inspector-slot')).toHaveClass('inspector-slot--collapsed');
    expect(document.querySelector('.workspace-layout')).toHaveClass('workspace-layout--inspector-collapsed');
  });

  it('collapses the inspector and re-expands it by reselecting the device', async () => {
    const user = userEvent.setup();
    renderInventory();

    await user.click(await screen.findByText('Edge router'));
    expect(await screen.findByRole('complementary', { name: 'Edge router inspector' })).toBeVisible();
    expect(document.querySelector('.workspace-layout')).not.toHaveClass('workspace-layout--inspector-collapsed');

    await user.click(screen.getByRole('button', { name: 'Collapse inspector' }));
    // Hidden via CSS, not unmounted -- see the state-preservation test below
    // for why. jsdom doesn't compute an external stylesheet's display: none,
    // so assert the collapsed class directly instead of DOM absence.
    const inspector = screen.getByRole('complementary', { name: 'Edge router inspector' });
    expect(inspector.closest('.inspector-slot')).toHaveClass('inspector-slot--collapsed');
    expect(localStorage.getItem('terraformer.inspector.collapsed')).toBe('1');

    // getByText would now match both the table row and the still-mounted
    // (CSS-hidden) inspector's own heading; the table row is the only match
    // with an actual button role.
    await user.click(screen.getByRole('button', { name: 'Inspect Edge router' }));
    expect(await screen.findByRole('complementary', { name: 'Edge router inspector' })).toBeVisible();
    expect(inspector.closest('.inspector-slot')).not.toHaveClass('inspector-slot--collapsed');
    expect(localStorage.getItem('terraformer.inspector.collapsed')).toBe('0');
  });

  it('preserves inspector tab state across collapse and re-expand', async () => {
    const user = userEvent.setup();
    renderInventory();

    await user.click(await screen.findByText('Edge router'));
    await user.click(screen.getByRole('button', { name: 'Interfaces' }));
    expect(screen.getByRole('button', { name: 'Interfaces' })).toHaveClass('is-active');

    await user.click(screen.getByRole('button', { name: 'Collapse inspector' }));
    await user.click(screen.getByRole('button', { name: 'Inspect Edge router' }));

    // If collapsing had unmounted the inspector, re-expanding would create a
    // fresh instance and reset to the Overview tab -- and for a device with
    // an in-progress Configure preview, would silently discard it too.
    expect(await screen.findByRole('button', { name: 'Interfaces' })).toHaveClass('is-active');
  });
});

describe('InventoryPage refresh all', () => {
  const second: Device = { ...device, id: '5f7837b9-4bf2-49ab-8205-c9acbf15a31d', name: 'Core switch' };

  beforeEach(() => {
    vi.mocked(api.credentialProfiles).mockResolvedValue([credential]);
  });

  it('queues a refresh job for every registered device', async () => {
    const user = userEvent.setup();
    vi.mocked(api.devices).mockResolvedValue([device, second]);
    vi.mocked(api.refreshDevice).mockResolvedValue({
      id: 'a1b2c3d4-df32-4a9e-9df0-6e6f8a2b6a11',
      type: 'refresh_device',
      state: 'queued',
      device_id: device.id,
      result: null,
      error_code: null,
      error_message: null,
      created_at: '2026-07-12T01:00:00Z',
      updated_at: '2026-07-12T01:00:00Z',
      started_at: null,
      finished_at: null,
    });
    renderInventory();
    await screen.findByText('Edge router');

    await user.click(screen.getByRole('button', { name: 'Refresh all' }));

    expect(api.refreshDevice).toHaveBeenCalledWith(device.id);
    expect(api.refreshDevice).toHaveBeenCalledWith(second.id);
    expect(api.refreshDevice).toHaveBeenCalledTimes(2);
  });

  it('disables refresh all when the inventory is empty', async () => {
    vi.mocked(api.devices).mockResolvedValue([]);
    renderInventory();

    expect(await screen.findByRole('button', { name: 'Refresh all' })).toBeDisabled();
    expect(api.refreshDevice).not.toHaveBeenCalled();
  });
});
