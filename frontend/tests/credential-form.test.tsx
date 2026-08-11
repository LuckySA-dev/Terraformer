import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CredentialForm } from '../src/features/inventory/CredentialForm';
import type { CredentialProfile } from '../src/types/api';

const credential: CredentialProfile = {
  id: 'c6d6a5be-bf2e-4d6a-bda8-3a559f985631',
  name: 'Lab admin',
  has_username: true,
  has_password: true,
  has_enable_password: true,
  created_at: '2026-07-11T00:00:00Z',
  updated_at: '2026-07-11T00:00:00Z',
};

describe('CredentialForm', () => {
  it('requires a username and password when creating a new profile', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => Promise.resolve());
    render(<CredentialForm onSubmit={onSubmit} onCancel={vi.fn()} />);

    await user.type(screen.getByLabelText('Profile name'), 'New profile');
    await user.click(screen.getByRole('button', { name: 'Save encrypted profile' }));

    expect(await screen.findByText('Enter a username.')).toBeVisible();
    expect(screen.getByText('Enter the device password.')).toBeVisible();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submits the full profile shape on create', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => Promise.resolve());
    render(<CredentialForm onSubmit={onSubmit} onCancel={vi.fn()} />);

    await user.type(screen.getByLabelText('Profile name'), 'New profile');
    await user.type(screen.getByLabelText('Device username'), 'automation');
    await user.type(screen.getByLabelText('Device password'), 'hunter2');
    await user.click(screen.getByRole('button', { name: 'Save encrypted profile' }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: 'New profile',
      username: 'automation',
      password: 'hunter2',
    });
  });

  it('prefills the name and leaves secrets blank when editing', () => {
    render(<CredentialForm credential={credential} onSubmit={vi.fn()} onCancel={vi.fn()} />);

    expect(screen.getByLabelText('Profile name')).toHaveValue('Lab admin');
    expect(screen.getByLabelText('Device username')).toHaveValue('');
    expect(screen.getByLabelText('Device password')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeVisible();
  });

  it('omits blank secrets on edit, keeping the stored values unchanged', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => Promise.resolve());
    render(<CredentialForm credential={credential} onSubmit={onSubmit} onCancel={vi.fn()} />);

    await user.clear(screen.getByLabelText('Profile name'));
    await user.type(screen.getByLabelText('Profile name'), 'Renamed profile');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(onSubmit).toHaveBeenCalledWith({ name: 'Renamed profile' });
  });

  it('includes a changed password without touching the username', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => Promise.resolve());
    render(<CredentialForm credential={credential} onSubmit={onSubmit} onCancel={vi.fn()} />);

    await user.type(screen.getByLabelText('Device password'), 'new-password');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(onSubmit).toHaveBeenCalledWith({ name: 'Lab admin', password: 'new-password' });
  });

  it('sends clear_enable_password when the clear checkbox is used', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => Promise.resolve());
    render(<CredentialForm credential={credential} onSubmit={onSubmit} onCancel={vi.fn()} />);

    await user.click(screen.getByRole('checkbox', { name: /clear the saved enable password/i }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(onSubmit).toHaveBeenCalledWith({ name: 'Lab admin', clear_enable_password: true });
  });

  it('ignores a typed enable password once the clear checkbox is checked', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => Promise.resolve());
    render(<CredentialForm credential={credential} onSubmit={onSubmit} onCancel={vi.fn()} />);

    await user.type(screen.getByLabelText('Enable password'), 'stale-value');
    await user.click(screen.getByRole('checkbox', { name: /clear the saved enable password/i }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(onSubmit).toHaveBeenCalledWith({ name: 'Lab admin', clear_enable_password: true });
  });

  it('does not offer to clear an enable password that was never set', () => {
    render(
      <CredentialForm
        credential={{ ...credential, has_enable_password: false }}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.queryByRole('checkbox', { name: /clear the saved enable password/i }))
      .not.toBeInTheDocument();
  });
});
