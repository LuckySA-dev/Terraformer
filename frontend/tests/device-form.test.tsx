import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApiError } from '../src/api/client';
import { api } from '../src/api/network';
import { DeviceForm } from '../src/features/inventory/DeviceForm';
import type { CredentialProfile, Device } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    testCandidateConnection: vi.fn(),
  },
}));

const credential: CredentialProfile = {
  id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
  name: 'Lab admin',
  has_username: true,
  has_password: true,
  has_enable_password: false,
  created_at: '2026-07-11T00:00:00Z',
  updated_at: '2026-07-11T00:00:00Z',
};

const legacyDevice: Device = {
  id: '2ad0db14-5a87-4147-a4e7-c98f88322464',
  name: 'Legacy switch',
  management_address: '192.0.2.20',
  port: 22,
  vendor: 'cisco_iosxe',
  credential_profile_id: credential.id,
  ssh_compatibility: 'cisco_legacy',
  status: 'reachable',
  facts: {},
  capabilities: [],
  last_seen_at: null,
  last_error_code: null,
  created_at: '2026-07-11T00:00:00Z',
  updated_at: '2026-07-11T00:00:00Z',
};

async function completeForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Device name'), 'Core switch');
  await user.type(screen.getByLabelText('Management address'), '192.0.2.10');
  await user.selectOptions(screen.getByLabelText('Credential profile'), credential.id);
}

describe('DeviceForm explicit connection safety gate', () => {
  it('defaults new and discovery approval forms to modern SSH', () => {
    const props = {
      credentials: [credential],
      onSubmit: vi.fn(() => Promise.resolve()),
      onCancel: vi.fn(),
      onCreateCredential: vi.fn(),
    };
    const { unmount } = render(<DeviceForm {...props} />);

    expect(screen.getByRole('combobox', { name: 'SSH compatibility' })).toHaveValue('modern');
    unmount();

    render(
      <DeviceForm
        {...props}
        initial={{ management_address: '192.0.2.30', port: 2222 }}
      />,
    );
    expect(screen.getByRole('combobox', { name: 'SSH compatibility' })).toHaveValue('modern');
  });

  it('loads a saved compatibility mode when editing', () => {
    render(
      <DeviceForm
        device={legacyDevice}
        credentials={[credential]}
        onSubmit={vi.fn(() => Promise.resolve())}
        onCancel={vi.fn()}
        onCreateCredential={vi.fn()}
      />,
    );

    expect(screen.getByRole('combobox', { name: 'SSH compatibility' })).toHaveValue(
      'cisco_legacy',
    );
  });

  it('explains that legacy mode is a per-device exception without automatic fallback', async () => {
    const user = userEvent.setup();
    render(
      <DeviceForm
        credentials={[credential]}
        onSubmit={vi.fn(() => Promise.resolve())}
        onCancel={vi.fn()}
        onCreateCredential={vi.fn()}
      />,
    );

    await user.selectOptions(
      screen.getByRole('combobox', { name: 'SSH compatibility' }),
      'cisco_legacy',
    );

    expect(screen.getByText(/per-device exception/i)).toBeVisible();
    expect(screen.getByText(/never.*automatic fallback/i)).toBeVisible();
  });

  it('requires a separate unchecked acknowledgment for the Group1 last resort', async () => {
    const user = userEvent.setup();
    render(
      <DeviceForm
        credentials={[credential]}
        onSubmit={vi.fn(() => Promise.resolve())}
        onCancel={vi.fn()}
        onCreateCredential={vi.fn()}
      />,
    );

    await completeForm(user);
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'SSH compatibility' }),
      'cisco_legacy_group1',
    );

    expect(screen.getByText('Last-resort Group1 exception')).toBeVisible();
    expect(screen.getByRole('checkbox', { name: /accept the Group1 risk/i })).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Test connection' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/acknowledge/i);
    expect(api.testCandidateConnection).not.toHaveBeenCalled();
  });

  it('keeps save disabled until the exact candidate connection succeeds', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => Promise.resolve());
    vi.mocked(api.testCandidateConnection).mockResolvedValue({
      reachable: true,
      driver: 'cisco_iosxe',
      message: 'Read-only connection succeeded.',
      latency_ms: 17,
    });
    render(
      <DeviceForm
        credentials={[credential]}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        onCreateCredential={vi.fn()}
      />,
    );

    await completeForm(user);
    const save = screen.getByRole('button', { name: 'Save device' });
    expect(save).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Test connection' }));
    expect(await screen.findByText('Read-only connection successful')).toBeVisible();
    expect(api.testCandidateConnection).toHaveBeenCalledWith({
      name: 'Core switch',
      management_address: '192.0.2.10',
      port: 22,
      vendor: 'cisco_iosxe',
      credential_profile_id: credential.id,
      ssh_compatibility: 'modern',
      group1_risk_acknowledged: false,
    });
    await waitFor(() => expect(save).toBeEnabled());

    await user.click(save);
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        name: 'Core switch',
        management_address: '192.0.2.10',
        port: 22,
        vendor: 'cisco_iosxe',
        credential_profile_id: credential.id,
        ssh_compatibility: 'modern',
        group1_risk_acknowledged: false,
      }),
    );
  });

  it('invalidates a successful test when a connection field changes', async () => {
    const user = userEvent.setup();
    vi.mocked(api.testCandidateConnection).mockResolvedValue({
      reachable: true,
      driver: 'cisco_iosxe',
      message: 'Read-only connection succeeded.',
      latency_ms: 12,
    });
    render(
      <DeviceForm
        credentials={[credential]}
        onSubmit={vi.fn(() => Promise.resolve())}
        onCancel={vi.fn()}
        onCreateCredential={vi.fn()}
      />,
    );
    await completeForm(user);
    await user.click(screen.getByRole('button', { name: 'Test connection' }));
    const save = screen.getByRole('button', { name: 'Save device' });
    await waitFor(() => expect(save).toBeEnabled());

    const address = screen.getByLabelText('Management address');
    await user.clear(address);
    await user.type(address, '192.0.2.11');

    expect(save).toBeDisabled();
  });

  it('invalidates a successful test when compatibility mode changes', async () => {
    const user = userEvent.setup();
    vi.mocked(api.testCandidateConnection).mockResolvedValue({
      reachable: true,
      driver: 'cisco_iosxe',
      message: 'Read-only connection succeeded.',
      latency_ms: 12,
    });
    render(
      <DeviceForm
        credentials={[credential]}
        onSubmit={vi.fn(() => Promise.resolve())}
        onCancel={vi.fn()}
        onCreateCredential={vi.fn()}
      />,
    );
    await completeForm(user);
    await user.click(screen.getByRole('button', { name: 'Test connection' }));
    const save = screen.getByRole('button', { name: 'Save device' });
    await waitFor(() => expect(save).toBeEnabled());

    await user.selectOptions(
      screen.getByRole('combobox', { name: 'SSH compatibility' }),
      'cisco_legacy',
    );

    expect(save).toBeDisabled();
  });

  it('invalidates a successful Group1 test when its acknowledgment changes', async () => {
    const user = userEvent.setup();
    vi.mocked(api.testCandidateConnection).mockResolvedValue({
      reachable: true,
      driver: 'cisco_iosxe',
      message: 'Read-only connection succeeded.',
      latency_ms: 12,
    });
    render(
      <DeviceForm
        credentials={[credential]}
        onSubmit={vi.fn(() => Promise.resolve())}
        onCancel={vi.fn()}
        onCreateCredential={vi.fn()}
      />,
    );
    await completeForm(user);
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'SSH compatibility' }),
      'cisco_legacy_group1',
    );
    const acknowledgment = screen.getByRole('checkbox', { name: /accept the Group1 risk/i });
    await user.click(acknowledgment);
    await user.click(screen.getByRole('button', { name: 'Test connection' }));
    const save = screen.getByRole('button', { name: 'Save device' });
    await waitFor(() => expect(save).toBeEnabled());

    await user.click(acknowledgment);

    expect(save).toBeDisabled();
  });

  it('shows only the sanitized backend message and recommended action', async () => {
    const user = userEvent.setup();
    vi.mocked(api.testCandidateConnection).mockRejectedValue(
      new ApiError('Legacy SSH is disabled by server policy.', {
        status: 403,
        code: 'legacy_mode_disabled_by_policy',
        details: {
          phase: 'ssh_negotiation',
          retryable: false,
          recommended_action: 'Ask the local operator to enable this mode.',
          raw_error: 'raw-secret-marker',
        },
      }),
    );
    render(
      <DeviceForm
        credentials={[credential]}
        onSubmit={vi.fn(() => Promise.resolve())}
        onCancel={vi.fn()}
        onCreateCredential={vi.fn()}
      />,
    );
    await completeForm(user);
    await user.click(screen.getByRole('button', { name: 'Test connection' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Legacy SSH is disabled by server policy.');
    expect(alert).toHaveTextContent('Ask the local operator to enable this mode.');
    expect(alert).not.toHaveTextContent('raw-secret-marker');
    expect(alert).not.toHaveTextContent('ssh_negotiation');
  });

  it('shows an unreachable result and never unlocks save', async () => {
    const user = userEvent.setup();
    vi.mocked(api.testCandidateConnection).mockResolvedValue({
      reachable: false,
      driver: 'cisco_iosxe',
      message: 'Authentication failed.',
      latency_ms: 25,
    });
    render(
      <DeviceForm
        credentials={[credential]}
        onSubmit={vi.fn(() => Promise.resolve())}
        onCancel={vi.fn()}
        onCreateCredential={vi.fn()}
      />,
    );
    await completeForm(user);
    await user.click(screen.getByRole('button', { name: 'Test connection' }));

    expect(await screen.findByText('Device is unreachable')).toBeVisible();
    expect(screen.getByText('Authentication failed.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Save device' })).toBeDisabled();
  });
});
