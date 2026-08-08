import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/network';
import { AppState, QueryErrorState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';

export function FindingsTab({ snapshotId }: { snapshotId: string }) {
  const findings = useQuery({
    queryKey: ['analysis-findings', snapshotId],
    queryFn: () => api.analysisFindings(snapshotId),
  });

  if (findings.isPending) {
    return <AppState kind="loading" title="Loading findings" message="Fetching analysis findings." />;
  }
  if (findings.isError) {
    return <QueryErrorState error={findings.error} onRetry={() => void findings.refetch()} />;
  }
  if (findings.data.length === 0) {
    // Deliberate wording: the absence of findings is not proof of correctness.
    return <p className="analysis-empty">No findings within the analysed scope.</p>;
  }

  return (
    <ul className="analysis-findings">
      {findings.data.map((finding) => (
        <li key={finding.id}>
          <Badge tone={finding.severity === 'error' ? 'danger' : 'warning'}>
            {finding.category.replace(/_/g, ' ')}
          </Badge>
          <span className="mono">{finding.structure_name ?? '—'}</span>
          <span>{finding.detail}</span>
        </li>
      ))}
    </ul>
  );
}
