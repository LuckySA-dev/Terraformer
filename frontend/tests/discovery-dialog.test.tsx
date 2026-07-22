import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { api } from '../src/api/network';
import { DiscoveryDialog } from '../src/features/inventory/DiscoveryDialog';
import type { Job } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    startDiscovery: vi.fn(),
    job: vi.fn(),
  },
}));

const queuedJob: Job = {
  id: '4530ef90-e648-4cb6-b72a-14665d0ce350',
  type: 'discover_ssh',
  state: 'queued',
  device_id: null,
  result: null,
  error_code: null,
  error_message: null,
  created_at: '2026-07-12T02:00:00Z',
  updated_at: '2026-07-12T02:00:00Z',
  started_at: null,
  finished_at: null,
};

function TestProviders({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('DiscoveryDialog safety flow', () => {
  beforeEach(() => vi.clearAllMocks());

  it('starts a bounded scan and requires candidate approval', async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    vi.mocked(api.startDiscovery).mockResolvedValue(queuedJob);
    vi.mocked(api.job).mockResolvedValue({
      ...queuedJob,
      state: 'succeeded',
      result: {
        cidr: '192.0.2.0/30',
        ports: [22, 23],
        scanned_count: 4,
        concurrency: 2,
        candidates: [{ management_address: '192.0.2.1', port: 22 }],
        open_endpoints: [{ management_address: '192.0.2.1', port: 23 }],
      },
    });
    render(<DiscoveryDialog onApprove={onApprove} />, { wrapper: TestProviders });

    await user.type(screen.getByRole('textbox', { name: 'IPv4 network' }), '192.0.2.0/30');
    const portsInput = screen.getByRole('textbox', { name: 'TCP ports' });
    await user.clear(portsInput);
    await user.type(portsInput, '22, 23');
    await user.click(screen.getByRole('button', { name: 'Start discovery' }));

    expect(api.startDiscovery).toHaveBeenCalledWith({
      cidr: '192.0.2.0/30',
      ports: [22, 23],
      concurrency: 4,
      connect_timeout_seconds: 0.5,
      probe_delay_ms: 50,
    });
    expect(await screen.findByText('192.0.2.1:22')).toBeVisible();
    expect(screen.getByText(/192\.0\.2\.1:23/)).toBeVisible();
    expect(screen.getAllByRole('button', { name: /review and approve/i })).toHaveLength(1);
    expect(screen.getByText(/no devices added/i)).toBeVisible();
    expect(screen.queryByText('LEGACY SSH')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /review and approve/i }));
    expect(onApprove).toHaveBeenCalledWith(queuedJob.id, {
      management_address: '192.0.2.1',
      port: 22,
    });
  });

  it('rejects more than four ports before starting discovery', async () => {
    const user = userEvent.setup();
    render(<DiscoveryDialog onApprove={vi.fn()} />, { wrapper: TestProviders });

    await user.type(screen.getByRole('textbox', { name: 'IPv4 network' }), '192.0.2.0/30');
    const portsInput = screen.getByRole('textbox', { name: 'TCP ports' });
    await user.clear(portsInput);
    await user.type(portsInput, '22,23,2222,2200,2022');
    await user.click(screen.getByRole('button', { name: 'Start discovery' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('1 to 4');
    expect(api.startDiscovery).not.toHaveBeenCalled();
  });

  it('shows a start failure without inventing candidates', async () => {
    const user = userEvent.setup();
    vi.mocked(api.startDiscovery).mockRejectedValue(new Error('Queue unavailable'));
    render(<DiscoveryDialog onApprove={vi.fn()} />, { wrapper: TestProviders });

    await user.type(screen.getByRole('textbox', { name: 'IPv4 network' }), '192.0.2.0/30');
    await user.click(screen.getByRole('button', { name: 'Start discovery' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Queue unavailable');
    expect(screen.queryByRole('region', { name: 'Discovery candidates' })).not.toBeInTheDocument();
  });

  it('does not start another scan while the current job is active', async () => {
    const user = userEvent.setup();
    vi.mocked(api.startDiscovery).mockResolvedValue(queuedJob);
    vi.mocked(api.job).mockResolvedValue(queuedJob);
    render(<DiscoveryDialog onApprove={vi.fn()} />, { wrapper: TestProviders });

    await user.type(screen.getByRole('textbox', { name: 'IPv4 network' }), '192.0.2.0/30');
    const startButton = screen.getByRole('button', { name: 'Start discovery' });
    await user.click(startButton);

    expect(await screen.findByText('Scanning bounded range')).toBeVisible();
    expect(startButton).toBeDisabled();
    await user.click(startButton);
    expect(api.startDiscovery).toHaveBeenCalledTimes(1);
  });
});
