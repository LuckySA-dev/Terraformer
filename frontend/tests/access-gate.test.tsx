import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { AccessGate } from '../src/features/access/AccessGate';
import type { HealthResponse } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    health: vi.fn(),
    setupStatus: vi.fn(),
    setup: vi.fn(),
    session: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  },
}));

const healthy: HealthResponse = {
  status: 'ok',
  version: '0.1.0',
  checks: {
    database: { status: 'ok' },
    redis: { status: 'ok' },
    worker: { status: 'ok' },
  },
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('AccessGate', () => {
  it('shows the secure first-run setup when the local API is healthy and unconfigured', async () => {
    vi.mocked(api.health).mockResolvedValue(healthy);
    vi.mocked(api.setupStatus).mockResolvedValue({ configured: false });

    render(
      <AccessGate>{() => <div>Workspace</div>}</AccessGate>,
      { wrapper: TestProviders },
    );

    expect(await screen.findByRole('heading', { name: 'Secure this local workspace' })).toBeVisible();
    expect(screen.getByLabelText('Master password')).toHaveAttribute('autocomplete', 'new-password');
    expect(screen.getByText(/Secrets stay server-side/i)).toBeVisible();
    expect(screen.queryByText('Workspace')).not.toBeInTheDocument();
  });

  it('renders a disconnected state without attempting setup when the API cannot be reached', async () => {
    vi.mocked(api.health).mockRejectedValue(new TypeError('Failed to fetch'));

    render(
      <AccessGate>{() => <div>Workspace</div>}</AccessGate>,
      { wrapper: TestProviders },
    );

    expect(await screen.findByRole('heading', { name: 'Local service disconnected' })).toBeVisible();
    expect(api.setupStatus).not.toHaveBeenCalled();
  });

  it('shows sign-in instead of the workspace for an unauthenticated configured install', async () => {
    vi.mocked(api.health).mockResolvedValue(healthy);
    vi.mocked(api.setupStatus).mockResolvedValue({ configured: true });
    vi.mocked(api.session).mockResolvedValue({ authenticated: false });

    render(
      <AccessGate>{() => <div>Workspace</div>}</AccessGate>,
      { wrapper: TestProviders },
    );

    expect(await screen.findByRole('heading', { name: 'Unlock Terraformer' })).toBeVisible();
    expect(screen.getByLabelText('Master password')).toHaveAttribute('autocomplete', 'current-password');
    expect(screen.queryByText('Workspace')).not.toBeInTheDocument();
  });
});
