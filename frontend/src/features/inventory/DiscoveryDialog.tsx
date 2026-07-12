import { useMutation, useQuery } from '@tanstack/react-query';
import { Radar, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { api } from '../../api/network';
import { AppState, InlineNotice, QueryErrorState } from '../../components/ui/AppState';
import { Button } from '../../components/ui/Button';
import { InputField } from '../../components/ui/FormField';
import type { DiscoveryCandidate, DiscoveryInput, DiscoveryResult } from '../../types/api';

interface DiscoveryDialogProps {
  onApprove: (jobId: string, candidate: DiscoveryCandidate) => void;
}

const finished = new Set(['succeeded', 'failed', 'cancelled']);

export function DiscoveryDialog({ onApprove }: DiscoveryDialogProps) {
  const [cidr, setCidr] = useState('');
  const [jobId, setJobId] = useState<string>();
  const start = useMutation({
    mutationFn: (input: DiscoveryInput) => api.startDiscovery(input),
    onSuccess: (job) => setJobId(job.id),
  });
  const job = useQuery({
    queryKey: ['jobs', jobId],
    queryFn: () => api.job(jobId ?? ''),
    enabled: jobId !== undefined,
    retry: false,
    refetchInterval: (query) =>
      query.state.data !== undefined && finished.has(query.state.data.state) ? false : 1_000,
  });
  const result =
    job.data?.type === 'discover_ssh' && job.data.state === 'succeeded'
      ? (job.data.result as unknown as DiscoveryResult)
      : undefined;
  const scanActive =
    jobId !== undefined && (job.data === undefined || !finished.has(job.data.state));

  if (job.isError) {
    return <QueryErrorState error={job.error} onRetry={() => void job.refetch()} compact />;
  }

  return (
    <div className="inspector-section-stack">
      <InlineNotice tone="warning" title="Explicit bounded scan">
        Scans only the exact IPv4 CIDR entered below, up to 64 addresses. Open ports become candidates;
        no device is added automatically.
      </InlineNotice>
      <form
        className="stack-form"
        onSubmit={(event) => {
          event.preventDefault();
          start.mutate({
            cidr: cidr.trim(),
            port: 22,
            concurrency: 4,
            connect_timeout_seconds: 0.5,
            probe_delay_ms: 50,
          });
        }}
      >
        <InputField
          label="IPv4 network"
          placeholder="192.0.2.0/29"
          value={cidr}
          onChange={(event) => setCidr(event.target.value)}
          required
          spellCheck={false}
          hint="Maximum 64 addresses / SSH port 22 / concurrency 4"
        />
        <Button
          type="submit"
          variant="primary"
          busy={start.isPending || scanActive}
          disabled={!cidr.trim() || scanActive}
        >
          <Radar size={16} /> Start discovery
        </Button>
      </form>
      {start.error === null ? null : (
        <div className="form-error" role="alert">
          {start.error.message}
        </div>
      )}
      {scanActive ? (
        <AppState
          kind="loading"
          title="Scanning bounded range"
          message="The worker is probing SSH port 22 at the configured safe rate..."
          compact
        />
      ) : null}
      {job.data?.state === 'failed' ? (
        <AppState
          kind="error"
          title="Discovery failed"
          message={job.data.error_message ?? 'The bounded scan could not complete.'}
          compact
        />
      ) : null}
      {result?.candidates.length === 0 ? (
        <AppState
          kind="empty"
          title="No SSH candidates found"
          message={`Scanned ${String(result.scanned_count)} addresses. No devices were added.`}
          compact
        />
      ) : null}
      {!result?.candidates.length ? null : (
        <section className="discovery-results" aria-label="Discovery candidates">
          <div>
            <strong>{result.candidates.length} candidates</strong>
            <span>{result.cidr} / no devices added</span>
          </div>
          {result.candidates.map((candidate) => (
            <button
              key={`${candidate.management_address}:${String(candidate.port)}`}
              type="button"
              onClick={() => onApprove(jobId ?? '', candidate)}
            >
              <span className="mono">{candidate.management_address}:{candidate.port}</span>
              <span><ShieldCheck size={14} /> Review and approve</span>
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
