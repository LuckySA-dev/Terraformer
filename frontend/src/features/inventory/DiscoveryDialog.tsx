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
  const [portInput, setPortInput] = useState('22');
  const [portError, setPortError] = useState<string>();
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
        Scans only the exact IPv4 CIDR and selected TCP ports, up to 256 endpoint checks. Only
        endpoints that identify as SSH become candidates; no device is added automatically.
      </InlineNotice>
      <form
        className="stack-form"
        onSubmit={(event) => {
          event.preventDefault();
          const ports = [
            ...new Set(portInput.split(',').map((value) => Number(value.trim()))),
          ];
          if (
            ports.length === 0 ||
            ports.length > 4 ||
            ports.some((port) => !Number.isInteger(port) || port < 1 || port > 65_535)
          ) {
            setPortError('Enter 1 to 4 TCP ports between 1 and 65535.');
            return;
          }
          setPortError(undefined);
          start.mutate({
            cidr: cidr.trim(),
            ports,
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
          hint="Maximum 64 addresses"
        />
        <InputField
          label="TCP ports"
          value={portInput}
          onChange={(event) => setPortInput(event.target.value)}
          error={portError}
          required
          spellCheck={false}
          hint="Comma-separated; maximum 4 ports and 256 endpoint checks"
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
          message="The worker is passively checking selected TCP ports for SSH identification..."
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
          message={`Checked ${String(result.scanned_count)} endpoints. No devices were added.`}
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
      {!result?.open_endpoints.length ? null : (
        <InlineNotice tone="warning" title="Open endpoints not identified as SSH">
          {result.open_endpoints
            .map((endpoint) => `${endpoint.management_address}:${String(endpoint.port)}`)
            .join(', ')}{' '}
          — informational only; these endpoints cannot be approved.
        </InlineNotice>
      )}
    </div>
  );
}
