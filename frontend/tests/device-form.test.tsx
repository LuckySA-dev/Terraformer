import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../src/api/network';
import { DeviceForm } from '../src/features/inventory/DeviceForm';
import type { CredentialProfile } from '../src/types/api';

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

async function completeForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Device name'), 'Core switch');
  await user.type(screen.getByLabelText('Management address'), '192.0.2.10');
  await user.selectOptions(screen.getByLabelText('Credential profile'), credential.id);
}

describe('DeviceForm explicit connection safety gate', () => {
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
    await waitFor(() => expect(save).toBeEnabled());

    await user.click(save);
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        name: 'Core switch',
        management_address: '192.0.2.10',
        port: 22,
        vendor: 'cisco_iosxe',
        credential_profile_id: credential.id,
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
