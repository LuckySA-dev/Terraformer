import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api } from '../../api/network';
import { AppState, InlineNotice, QueryErrorState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { CompletenessBanner } from './CompletenessBanner';
import { FilterCheckTab } from './FilterCheckTab';
import { FindingsTab } from './FindingsTab';
import { PathCheckTab } from './PathCheckTab';

type TabId = 'findings' | 'path' | 'filter';

export function AnalysisPage() {
  const [tab, setTab] = useState<TabId>('findings');
  const queryClient = useQueryClient();
  const snapshots = useQuery({
    queryKey: ['analysis-snapshots'],
    queryFn: () => api.analysisSnapshots(),
  });
  const start = useMutation({
    mutationFn: () => api.startAnalysis(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['analysis-snapshots'] });
    },
  });

  if (snapshots.isPending) {
    return <AppState kind="loading" title="Loading analysis" message="Fetching analysis snapshots." />;
  }
  if (snapshots.isError) {
    return <QueryErrorState error={snapshots.error} onRetry={() => void snapshots.refetch()} />;
  }

  const latest = snapshots.data[0];
  if (latest === undefined) {
    return (
      <section className="analysis-page">
        <InlineNotice tone="safe" title="Read-only analysis">
          Analysis reasons over stored configuration snapshots. It never contacts a device.
        </InlineNotice>
        <Button variant="primary" onClick={() => start.mutate()} busy={start.isPending}>
          Analyse network
        </Button>
      </section>
    );
  }

  return (
    <section className="analysis-page">
      <header className="analysis-page__header">
        <div>
          <h2>Configuration analysis</h2>
          <Badge tone="purple">{latest.evidence}</Badge>
          <Badge tone={latest.status === 'ready' ? 'success' : 'warning'}>{latest.status}</Badge>
        </div>
        <Button onClick={() => start.mutate()} busy={start.isPending}>
          {latest.status === 'expired' ? 'Re-parse' : 'Analyse again'}
        </Button>
      </header>

      <CompletenessBanner completeness={latest.completeness} />

      {latest.status === 'expired' ? (
        <InlineNotice tone="warning" title="This analysis is no longer loaded">
          The analysis service restarted and lost the parsed snapshot. Re-parse uses the same
          stored configurations and contacts no device.
        </InlineNotice>
      ) : null}
      {latest.findings_truncated ? (
        <InlineNotice tone="warning" title="Findings were truncated">
          The finding limit was reached, so this list is incomplete.
        </InlineNotice>
      ) : null}

      <div className="analysis-tabs" role="tablist" aria-label="Analysis views">
        {(
          [
            ['findings', 'Findings'],
            ['path', 'Path check'],
            ['filter', 'Filter check'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? 'is-active' : ''}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'findings' ? <FindingsTab snapshotId={latest.id} /> : null}
      {tab === 'path' ? <PathCheckTab snapshotId={latest.id} /> : null}
      {tab === 'filter' ? <FilterCheckTab snapshotId={latest.id} /> : null}
    </section>
  );
}
