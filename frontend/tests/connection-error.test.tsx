import { render, screen } from '@testing-library/react';
import { ApiError } from '../src/api/client';
import { ConnectionError } from '../src/components/ui/ConnectionError';
import { SSH_MODES_BY_VENDOR } from '../src/types/api';

const apiError = (code: string, message: string, details: Record<string, unknown>) =>
  new ApiError(message, { status: 502, code, details });

describe('ConnectionError', () => {
  it('names the stage that failed instead of only the message', () => {
    render(
      <ConnectionError
        error={apiError('legacy_ssh_negotiation_failed', 'SSH negotiation failed', {
          phase: 'ssh_negotiation',
          retryable: false,
        })}
      />,
    );

    const failed = screen.getByText('Agree on encryption').closest('li');
    expect(failed).toHaveTextContent('failed here');
    expect(screen.getByText('Reach the device').closest('li')).not.toHaveTextContent('failed here');
  });

  it('explains that a negotiation failure is not a password problem', () => {
    render(
      <ConnectionError
        error={apiError('legacy_ssh_negotiation_failed', 'SSH negotiation failed', {
          phase: 'ssh_negotiation',
        })}
      />,
    );

    expect(screen.getByText(/not a password problem/)).toBeVisible();
    // Names the floor a client setting cannot get under, and the device-side
    // fix -- telling an operator already on Very Old SSH to "raise the mode"
    // sent them down a path with no end.
    expect(screen.getByText(/Below 768 bits no client setting can help/)).toBeVisible();
    expect(screen.getByText(/crypto key generate rsa modulus 2048/)).toBeVisible();
  });

  it('shows the backend recommended action verbatim', () => {
    render(
      <ConnectionError
        error={apiError('device_authentication_failed', 'The device rejected the credentials', {
          phase: 'authentication',
          recommended_action: 'Verify the selected credential profile.',
        })}
      />,
    );

    expect(screen.getByText('Verify the selected credential profile.')).toBeVisible();
  });

  it('points GNS3 users at the right port when the connection is refused', () => {
    render(
      <ConnectionError
        error={apiError('device_connection_refused', 'Connection refused', {
          phase: 'tcp_connection',
        })}
      />,
    );

    expect(screen.getByText(/console port is usually not 22/)).toBeVisible();
  });

  it('falls back cleanly for a non-API failure', () => {
    render(<ConnectionError error={new TypeError('offline')} fallback="Could not complete." />);

    expect(screen.getByText('Could not complete.')).toBeVisible();
    expect(screen.queryByLabelText('Connection stages')).not.toBeInTheDocument();
  });
});

describe('vendor compatibility rules', () => {
  it('offers Cisco-only legacy modes to Cisco alone', () => {
    // Mirrors _CISCO_ONLY_MODES in backend/app/api/ssh_trust.py.
    expect(SSH_MODES_BY_VENDOR.cisco_iosxe).toContain('cisco_legacy_group1');
    expect(SSH_MODES_BY_VENDOR.fortinet_fortios).not.toContain('cisco_legacy');
    expect(SSH_MODES_BY_VENDOR.fortinet_fortios).not.toContain('cisco_legacy_group1');
    expect(SSH_MODES_BY_VENDOR.generic).not.toContain('cisco_legacy');
  });

  it('offers very_old_ssh only to the vendors the backend allows', () => {
    // Mirrors _VERY_OLD_VENDORS in backend/app/api/ssh_trust.py.
    expect(SSH_MODES_BY_VENDOR.cisco_iosxe).toContain('very_old_ssh');
    expect(SSH_MODES_BY_VENDOR.fortinet_fortios).toContain('very_old_ssh');
    expect(SSH_MODES_BY_VENDOR.generic).not.toContain('very_old_ssh');
  });

  it('always allows modern', () => {
    for (const modes of Object.values(SSH_MODES_BY_VENDOR)) {
      expect(modes).toContain('modern');
    }
  });
});
