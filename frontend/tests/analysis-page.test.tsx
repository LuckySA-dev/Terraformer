import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { api } from '../src/api/network';
import { AnalysisPage } from '../src/features/analysis/AnalysisPage';
import type { AnalysisSnapshot } from '../src/types/api';

vi.mock('../src/api/network', () => ({
  api: {
    analysisSnapshots: vi.fn(),
    startAnalysis: vi.fn(),
    analysisFindings: vi.fn(),
    pathCheck: vi.fn(),
    filterCheck: vi.fn(),
    devices: vi.fn(),
  },
}));

const snapshot: AnalysisSnapshot = {
  id: '3f1b0b2e-6a0e-4a3f-9a1e-0c2c1f9a7b11',
  status: 'ready',
  evidence: 'INFERRED',
  parse_warning_count: 0,
  findings_truncated: false,
  failure_code: null,
  completeness: {
    registered_device_count: 12,
    analysed_device_count: 7,
    observed_link_count: 9,
    exclusions: [
      { reason: 'no_snapshot', count: 3 },
      { reason: 'unsupported_vendor', count: 2 },
    ],
    oldest_config_at: '2026-08-02T00:00:00Z',
    newest_config_at: '2026-08-08T00:00:00Z',
  },
  created_at: '2026-08-08T00:00:00Z',
  updated_at: '2026-08-08T00:00:00Z',
};

const renderPage = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AnalysisPage />
    </QueryClientProvider>,
  );
};

describe('AnalysisPage', () => {
  beforeEach(() => {
    vi.mocked(api.analysisSnapshots).mockResolvedValue([snapshot]);
    vi.mocked(api.analysisFindings).mockResolvedValue([]);
    vi.mocked(api.devices).mockResolvedValue([]);
  });

  it('always discloses how complete the analysis was', async () => {
    renderPage();

    expect(await screen.findByText(/Analysed 7 of 12 registered devices/)).toBeVisible();
    expect(screen.getByText(/3 have no configuration snapshot/)).toBeVisible();
    expect(screen.getByText(/2 run a vendor that is not supported/)).toBeVisible();
    expect(screen.getByText(/9 observed links supplied as layer-1 topology/)).toBeVisible();
  });

  it('labels the result as inferred, never as verified', async () => {
    renderPage();

    expect(await screen.findByText('INFERRED')).toBeVisible();
    expect(screen.queryByText(/healthy/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/OBSERVED/)).not.toBeInTheDocument();
  });

  it('says no findings within the analysed scope rather than claiming correctness', async () => {
    renderPage();

    expect(
      await screen.findByText('No findings within the analysed scope.'),
    ).toBeVisible();
  });

  it('offers re-parse when the snapshot has expired', async () => {
    vi.mocked(api.analysisSnapshots).mockResolvedValue([
      { ...snapshot, status: 'expired' },
    ]);

    renderPage();

    const reparse = await screen.findByRole('button', { name: /Re-parse/ });
    await userEvent.click(reparse);

    await waitFor(() => expect(api.startAnalysis).toHaveBeenCalled());
  });

  it('explains what to do when no analysis exists yet', async () => {
    vi.mocked(api.analysisSnapshots).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByRole('button', { name: /Analyse network/ })).toBeVisible();
  });
});
