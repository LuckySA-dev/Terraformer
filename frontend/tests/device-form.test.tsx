import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApiError } from '../src/api/client';
import { api } from '../src/api/network';
import { DeviceForm } from '../src/features/inventory/DeviceForm';
import type { CredentialProfile, Device } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    collectHostKeyCandidate: vi.fn(),
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

const hostKeyCandidate = {
  id: 'b6871493-41ea-4f96-b126-c09e033fd6e2',
  algorithm: 'ssh-rsa',
  fingerprint: 'SHA256:fixture',
  expires_at: '2026-08-06T12:15:00Z',
};

async function completeForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Device name'), 'Core switch');
  await user.type(screen.getByLabelText('Management address'), '192.0.2.10');
  await user.selectOptions(screen.getByLabelText('Credential profile'), credential.id);
}

async function inspectAndConfirm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Inspect SSH host key' }));
  await user.click(await screen.findByRole('checkbox', { name: /verified this fingerprint/i }));
}

describe('DeviceForm explicit connection safety gate', () => {
  beforeEach(() => {
    vi.mocked(api.collectHostKeyCandidate).mockResolvedValue(hostKeyCandidate);
  });

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

  it('requires a separate unchecked acknowledgment for Very Old SSH', async () => {
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
      'very_old_ssh',
    );

    expect(screen.getByText('Last-resort obsolete cryptography exception')).toBeVisible();
    expect(screen.getByRole('checkbox', { name: /accept the Very Old SSH/i })).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Test connection' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/acknowledge the Very Old SSH/i);
    expect(api.testCandidateConnection).not.toHaveBeenCalled();
  });

  it('restricts SSH compatibility options when Fortinet driver is selected', async () => {
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
      screen.getByRole('combobox', { name: 'Platform driver' }),
      'fortinet_fortios',
    );

    const select = screen.getByRole('combobox', { name: 'SSH compatibility' });
    expect(select.querySelector('option[value="modern"]')).not.toBeNull();
    expect(select.querySelector('option[value="very_old_ssh"]')).not.toBeNull();
    expect(select.querySelector('option[value="cisco_legacy"]')).toBeNull();
    expect(select.querySelector('option[value="cisco_legacy_group1"]')).toBeNull();
  });

  it('requires explicit fingerprint confirmation before testing credentials', async () => {
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
    await user.click(screen.getByRole('button', { name: 'Inspect SSH host key' }));

    expect(await screen.findByText('SHA256:fixture')).toBeVisible();
    expect(screen.getByText('ssh-rsa')).toBeVisible();
    const test = screen.getByRole('button', { name: 'Test connection' });
    expect(test).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /verified this fingerprint/i }));
    expect(test).toBeEnabled();
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

    await inspectAndConfirm(user);
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
      very_old_risk_acknowledged: false,
      host_key_candidate_id: hostKeyCandidate.id,
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
        very_old_risk_acknowledged: false,
        host_key_candidate_id: hostKeyCandidate.id,
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
    await inspectAndConfirm(user);
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
    await inspectAndConfirm(user);
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
    await inspectAndConfirm(user);
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
    await inspectAndConfirm(user);
    await user.click(screen.getByRole('button', { name: 'Test connection' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Legacy SSH is disabled by server policy.');
    expect(alert).toHaveTextContent('Ask the local operator to enable this mode.');
    expect(alert).not.toHaveTextContent('raw-secret-marker');
    expect(alert).not.toHaveTextContent('ssh_negotiation');
  });

  it('guides the operator to re-inspect a changed host key', async () => {
    const user = userEvent.setup();
    vi.mocked(api.testCandidateConnection).mockRejectedValue(
      new ApiError('The SSH host key changed.', {
        status: 409,
        code: 'device_host_key_changed',
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
    await inspectAndConfirm(user);
    await user.click(screen.getByRole('button', { name: 'Test connection' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The SSH host key changed. Inspect and verify again.',
    );
    expect(screen.queryByText('SHA256:fixture')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Inspect SSH host key' })).toBeEnabled();
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
    await inspectAndConfirm(user);
    await user.click(screen.getByRole('button', { name: 'Test connection' }));

    expect(await screen.findByText('Device is unreachable')).toBeVisible();
    expect(screen.getByText('Authentication failed.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Save device' })).toBeDisabled();
  });
});
