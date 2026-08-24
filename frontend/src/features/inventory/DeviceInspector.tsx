import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  Braces,
  Check,
  ChevronRight,
  CircleGauge,
  CircleX,
  Clock3,
  Download,
  FileLock2,
  KeyRound,
  LoaderCircle,
  ListTree,
  Network,
  Pencil,
  PlugZap,
  RefreshCw,
  Router,
  Server,
  Settings2,
  ShieldCheck,
  SquareTerminal,
  Trash2,
  Waypoints,
  WifiOff,
  X,
} from 'lucide-react';
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/network';
import type {
  ChangePlan,
  ChangeType,
  ConfigSnapshot,
  Device,
  DiagnosticAction,
  DiagnosticResult,
  DeviceFacts,
  DeviceInterface,
  DeviceNeighbor,
  Job,
} from '../../types/api';
import { AppState, InlineNotice, QueryErrorState } from '../../components/ui/AppState';
import { ConnectionError } from '../../components/ui/ConnectionError';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { InputField, SelectField } from '../../components/ui/FormField';
import { formatDateTime, formatRelativeTime, formatUptime, titleCase } from '../../lib/format';
import { EventTimeline } from './EventTimeline';

const TerminalPanel = lazy(() =>
  import('./TerminalPanel').then((module) => ({ default: module.TerminalPanel })),
);

type InspectorTab =
  | 'overview'
  | 'interfaces'
  | 'neighbors'
  | 'diagnostics'
  | 'terminal'
  | 'snapshots'
  | 'configure'
  | 'activity';

interface DeviceInspectorProps {
  device: Device | null;
  onClose: () => void;
  onEdit: (device: Device) => void;
  onDelete: (device: Device) => void;
}

const finalJobStates = new Set(['succeeded', 'failed', 'cancelled']);
const diagnosticActions: {
  action: DiagnosticAction;
  capability: string;
  label: string;
  targetRequired?: boolean;
}[] = [
  { action: 'routing_table', capability: 'routing', label: 'Routing table' },
  { action: 'arp_table', capability: 'arp', label: 'ARP table' },
  { action: 'mac_table', capability: 'mac', label: 'MAC address table' },
  { action: 'ping', capability: 'ping', label: 'Ping', targetRequired: true },
  {
    action: 'traceroute',
    capability: 'traceroute',
    label: 'Traceroute',
    targetRequired: true,
  },
];

function stateTone(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'reachable') return 'success';
  if (status === 'unreachable') return 'danger';
  return 'warning';
}

function downloadDiagnostic(result: DiagnosticResult): void {
  const url = URL.createObjectURL(new Blob([result.output], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `diagnostic-${result.action}.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

function Detail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="detail-row">
      <span>{label}</span>
      <strong className={mono ? 'mono' : ''}>{value}</strong>
    </div>
  );
}

function FactsGrid({ facts }: { facts: DeviceFacts }) {
  return (
    <div className="facts-grid">
      <div className="fact-card">
        <Server size={16} />
        <span>Hostname</span>
        <strong>{facts.hostname ?? 'Unavailable'}</strong>
      </div>
      <div className="fact-card">
        <Router size={16} />
        <span>Model</span>
        <strong>{facts.model ?? 'Unavailable'}</strong>
      </div>
      <div className="fact-card">
        <Braces size={16} />
        <span>OS version</span>
        <strong>{facts.os_version ?? 'Unavailable'}</strong>
      </div>
      <div className="fact-card">
        <Clock3 size={16} />
        <span>Uptime</span>
        <strong>{facts.uptime ?? formatUptime(facts.uptime_seconds)}</strong>
      </div>
    </div>
  );
}

function OverviewTab({ device }: { device: Device }) {
  const facts = useQuery({
    queryKey: ['devices', device.id, 'facts'],
    queryFn: () => api.facts(device.id),
    retry: false,
  });
  const test = useMutation({ mutationFn: () => api.testDeviceConnection(device.id) });
  const capabilities = device.capabilities;
  const canApply = capabilities.some((item) => item.name === 'apply' && item.supported);

  return (
    <div className="inspector-section-stack">
      <InlineNotice tone="safe" title={canApply ? 'Structured writes require explicit apply' : 'Observed state only'}>
        {canApply
          ? 'This driver supports a small set of vetted structured changes, on the Configure tab. Every change is previewed before anything is sent, and applying can change the device.'
          : 'This inspector can read and snapshot device state. Configuration writes are not available for this driver.'}
      </InlineNotice>
      <section className="inspector-section">
        <div className="inspector-section__heading">
          <h3>Connection</h3>
          <Button size="small" onClick={() => test.mutate()} busy={test.isPending}>
            <PlugZap size={14} /> Test now
          </Button>
        </div>
        <Detail label="Management address" value={`${device.management_address}:${String(device.port)}`} mono />
        <Detail label="Driver" value={device.vendor === 'generic' ? 'Generic · connection test only' : 'Cisco IOS / IOS-XE'} />
        <Detail label="Last observed" value={formatRelativeTime(device.last_seen_at)} />
        {test.data === undefined ? null : (
          <div
            className={`mini-result ${test.data.reachable ? 'mini-result--success' : 'mini-result--error'}`}
            role="status"
          >
            {test.data.reachable ? <Check size={14} /> : <WifiOff size={14} />}
            <span>{test.data.message}</span>
          </div>
        )}
        {test.error === null ? null : (
          <div className="mini-result mini-result--error" role="alert">
            <WifiOff size={14} /> <span>{test.error.message}</span>
          </div>
        )}
      </section>
      <section className="inspector-section">
        <div className="inspector-section__heading">
          <h3>Device facts</h3>
          <Badge tone="info">READ ONLY</Badge>
        </div>
        {facts.isPending ? (
          <AppState kind="loading" title="Reading facts" message="Waiting for locally stored device facts…" compact />
        ) : facts.isError ? (
          <QueryErrorState error={facts.error} onRetry={() => void facts.refetch()} compact />
        ) : (
          <FactsGrid facts={facts.data.facts} />
        )}
      </section>
      <section className="inspector-section">
        <div className="inspector-section__heading">
          <h3>Capabilities</h3>
          <Badge tone="purple">DRIVER DECLARED</Badge>
        </div>
        {capabilities.length === 0 ? (
          <AppState
            kind="unsupported"
            title="Capabilities not reported"
            message="Refresh observed state to probe this driver. All writes remain blocked."
            compact
          />
        ) : (
          <div className="capability-list">
            {capabilities.map((capability) => (
              <div key={capability.name}>
                <span>{titleCase(capability.name)}</span>
                <Badge tone={capability.supported ? 'success' : 'neutral'} dot>
                  {capability.supported ? `Available · Level ${capability.safety_level}` : 'Unsupported'}
                </Badge>
              </div>
            ))}
          </div>
        )}
        {canApply ? null : (
          <AppState
            kind="unsupported"
            title="Configuration is unavailable"
            message="This driver has no verified write capability yet."
            compact
          />
        )}
      </section>
    </div>
  );
}

function InterfacesTab({ device }: { device: Device }) {
  const interfaces = useQuery({
    queryKey: ['devices', device.id, 'interfaces'],
    queryFn: () => api.interfaces(device.id),
    retry: false,
  });
  if (interfaces.isPending) {
    return <AppState kind="loading" title="Loading interfaces" message="Reading stored interface state…" />;
  }
  if (interfaces.isError) {
    return <QueryErrorState error={interfaces.error} onRetry={() => void interfaces.refetch()} />;
  }
  if (interfaces.data.length === 0) {
    return (
      <AppState
        kind="empty"
        title="No interfaces observed"
        message="Refresh this device to retrieve its read-only interface inventory."
      />
    );
  }
  return (
    <div className="interface-list">
      {interfaces.data.map((item: DeviceInterface) => (
        <article key={item.name} className="interface-row">
          <div className={`interface-row__status ${item.oper_up === true ? 'is-up' : 'is-down'}`} aria-hidden="true" />
          <div className="interface-row__main">
            <strong>{item.name}</strong>
            <span>{item.description ?? 'No description'}</span>
          </div>
          <div className="interface-row__meta">
            <Badge tone={item.oper_up === true ? 'success' : item.admin_up === false ? 'neutral' : 'danger'}>
              {item.admin_up === false ? 'disabled' : item.oper_up === true ? 'up' : 'down'}
            </Badge>
            <span>{item.speed_mbps === null ? '—' : `${String(item.speed_mbps)} Mb/s`}</span>
          </div>
        </article>
      ))}
    </div>
  );
}

function NeighborsTab({ device }: { device: Device }) {
  const neighbors = useQuery({
    queryKey: ['devices', device.id, 'neighbors'],
    queryFn: () => api.neighbors(device.id),
    retry: false,
  });
  if (neighbors.isPending) {
    return <AppState kind="loading" title="Loading neighbors" message="Reading stored CDP and LLDP observations…" />;
  }
  if (neighbors.isError) {
    return <QueryErrorState error={neighbors.error} onRetry={() => void neighbors.refetch()} />;
  }
  if (neighbors.data.length === 0) {
    return (
      <AppState
        kind="empty"
        title="No neighbors observed"
        message="Refresh this Cisco device to collect read-only CDP and LLDP observations."
      />
    );
  }
  return (
    <div className="neighbor-list">
      {neighbors.data.map((item: DeviceNeighbor) => (
        <article key={item.id} className="neighbor-row">
          <div className="neighbor-row__heading">
            <strong>{item.remote_device_name}</strong>
            <Badge tone="info">{item.protocol.toUpperCase()} · OBSERVED</Badge>
          </div>
          <Detail label="Local interface" value={item.local_interface} mono />
          <Detail label="Remote interface" value={item.remote_interface} mono />
          <Detail label="Management address" value={item.management_address ?? 'Unavailable'} mono />
          <Detail label="Platform" value={item.platform ?? 'Unavailable'} />
        </article>
      ))}
    </div>
  );
}

function DiagnosticsTab({
  device,
  job,
  running,
  error,
  onRun,
}: {
  device: Device;
  job: Job | undefined;
  running: boolean;
  error: string | undefined;
  onRun: (action: DiagnosticAction, target?: string) => void;
}) {
  const available = diagnosticActions.filter(({ capability }) =>
    device.capabilities.some((item) => item.name === capability && item.supported),
  );
  const [action, setAction] = useState<DiagnosticAction>(
    available[0]?.action ?? 'routing_table',
  );
  const [target, setTarget] = useState('');
  const selectedAction = diagnosticActions.find((item) => item.action === action);
  const result =
    job?.type === 'run_diagnostic' && job.state === 'succeeded'
      ? (job.result as unknown as DiagnosticResult)
      : undefined;

  if (available.length === 0) {
    return (
      <AppState
        kind="empty"
        title="Diagnostics unavailable"
        message="This driver has no verified routing, ARP, or MAC read capability."
      />
    );
  }

  return (
    <div className="inspector-section-stack">
      <InlineNotice tone="warning" title="Allowlisted device read">
        Runs one fixed show command through the background worker. Custom commands and targets are not accepted.
      </InlineNotice>
      <div className="diagnostic-actions">
        <SelectField
          label="Diagnostic"
          value={action}
          onChange={(event) => setAction(event.target.value as DiagnosticAction)}
        >
          {available.map((item) => (
            <option key={item.action} value={item.action}>{item.label}</option>
          ))}
        </SelectField>
        {selectedAction?.targetRequired === true ? (
          <InputField
            label="Exact IPv4 target"
            placeholder="198.51.100.10"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            required
            spellCheck={false}
            hint="One address only; CIDR, hostname, and command text are rejected"
          />
        ) : null}
        <Button
          size="small"
          onClick={() => onRun(action, selectedAction?.targetRequired === true ? target.trim() : undefined)}
          busy={running}
          disabled={selectedAction?.targetRequired === true && !target.trim()}
        >
          <ListTree size={14} /> Run read-only diagnostic
        </Button>
      </div>
      {error === undefined ? null : <div className="form-error" role="alert">{error}</div>}
      {job?.type === 'run_diagnostic' && job.state === 'failed' ? (
        <AppState
          kind="error"
          title="Diagnostic failed"
          message={job.error_message ?? 'The allowlisted diagnostic could not complete.'}
          compact
        />
      ) : null}
      {result === undefined ? null : (
        <div className="diagnostic-output">
          <div>
            <strong>{diagnosticActions.find((item) => item.action === result.action)?.label}</strong>
            <span>
              <Badge tone={result.truncated ? 'warning' : 'info'}>
                {result.truncated ? 'TRUNCATED' : 'SANITIZED'}
              </Badge>
              <Button size="small" variant="ghost" onClick={() => downloadDiagnostic(result)}>
                <Download size={12} /> Download sanitized output
              </Button>
            </span>
          </div>
          <pre>{result.output}</pre>
        </div>
      )}
    </div>
  );
}

function SnapshotDetail({ snapshot }: { snapshot: ConfigSnapshot }) {
  const detail = useQuery({
    queryKey: ['snapshots', snapshot.id],
    queryFn: () => api.snapshot(snapshot.id),
    retry: false,
  });
  if (detail.isPending) {
    return <AppState kind="loading" title="Opening encrypted snapshot" message="Decrypting on the local API…" compact />;
  }
  if (detail.isError) {
    return <QueryErrorState error={detail.error} onRetry={() => void detail.refetch()} compact />;
  }
  return (
    <div className="snapshot-detail-stack">
      <InlineNotice tone="warning" title="Sensitive local configuration">
        This decrypted view may contain device secrets. Do not copy it into logs, support tickets, or Git.
      </InlineNotice>
      <div className="snapshot-viewer">
      <div className="snapshot-viewer__bar">
        <span>
          <FileLock2 size={14} /> Running configuration · local view
        </span>
        <time dateTime={detail.data.created_at}>{formatDateTime(detail.data.created_at)}</time>
      </div>
      <pre>{detail.data.content ?? 'Snapshot content is unavailable.'}</pre>
      </div>
    </div>
  );
}

function SnapshotsTab({ device, onCapture, capturing }: { device: Device; onCapture: () => void; capturing: boolean }) {
  const [selectedId, setSelectedId] = useState<string>();
  const snapshots = useQuery({
    queryKey: ['snapshots', { deviceId: device.id }],
    queryFn: () => api.snapshots(device.id),
    retry: false,
  });
  const selected = snapshots.data?.find((snapshot) => snapshot.id === selectedId);

  if (snapshots.isPending) {
    return <AppState kind="loading" title="Loading snapshots" message="Reading immutable snapshot metadata…" />;
  }
  if (snapshots.isError) {
    return <QueryErrorState error={snapshots.error} onRetry={() => void snapshots.refetch()} />;
  }
  return (
    <div className="inspector-section-stack">
      <InlineNotice tone="info" title="Immutable and encrypted">
        Snapshot content is compressed and encrypted by the local API. Capturing is a read-only device operation.
      </InlineNotice>
      <div className="snapshot-actions">
        <div>
          <strong>Running configuration</strong>
          <span>{snapshots.data.length} stored snapshots</span>
        </div>
        <Button size="small" onClick={onCapture} busy={capturing}>
          <FileLock2 size={14} /> Capture snapshot
        </Button>
      </div>
      {snapshots.data.length === 0 ? (
        <AppState
          kind="empty"
          title="No snapshots yet"
          message="Capture the current running configuration without making any device changes."
          compact
        />
      ) : (
        <div className="snapshot-list">
          {snapshots.data.map((snapshot) => (
            <button key={snapshot.id} type="button" onClick={() => setSelectedId(snapshot.id)}>
              <FileLock2 size={15} />
              <span>
                <strong>{formatDateTime(snapshot.created_at)}</strong>
                <small>{snapshot.sha256.slice(0, 12)} · {snapshot.encryption}</small>
              </span>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
      )}
      {selected === undefined ? null : <SnapshotDetail snapshot={selected} />}
    </div>
  );
}

const changePlanStatusTone: Record<ChangePlan['status'], 'neutral' | 'success' | 'warning' | 'danger'> = {
  draft: 'neutral',
  applying: 'warning',
  applied: 'success',
  failed: 'danger',
  rolled_back: 'warning',
  rollback_failed: 'danger',
};

function ConfigureTab({ device }: { device: Device }) {
  const queryClient = useQueryClient();
  const [changeType, setChangeType] = useState<ChangeType>('interface_description');
  const [target, setTarget] = useState('');
  const [desiredValue, setDesiredValue] = useState('');
  const [plan, setPlan] = useState<ChangePlan | null>(null);

  const interfaces = useQuery({
    queryKey: ['devices', device.id, 'interfaces'],
    queryFn: () => api.interfaces(device.id),
    retry: false,
  });
  const history = useQuery({
    queryKey: ['change-plans', device.id],
    queryFn: () => api.listChangePlans(device.id),
    retry: false,
    // Apply runs in the background worker, so the status a plan lands on
    // arrives after the request that queued it. Poll only while one is
    // actually in flight.
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status === 'applying') === true ? 1_000 : false,
  });
  const preview = useMutation({
    mutationFn: () =>
      api.previewChange({
        device_id: device.id,
        change_type: changeType,
        target,
        desired_value: desiredValue,
      }),
    onSuccess: (result) => setPlan(result),
  });
  const apply = useMutation({
    mutationFn: (planId: string) => api.applyChangePlan(planId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['change-plans', device.id] });
    },
  });

  const canApply = device.capabilities.some((item) => item.name === 'apply' && item.supported);
  if (!canApply) {
    return (
      <AppState
        kind="empty"
        title="Structured configuration unavailable"
        message="This driver has no verified apply capability for this vendor yet."
      />
    );
  }

  const resetPlan = () => setPlan(null);

  return (
    <div className="inspector-section-stack">
      <InlineNotice tone="warning" title="Best effort, not auto-rollback">
        Preview shows the exact commands and risk before anything is sent. Applying can change the
        device; recovery on failure requires connectivity.
      </InlineNotice>
      <div className="configure-form">
        <SelectField
          label="Change type"
          value={changeType}
          onChange={(event) => {
            setChangeType(event.target.value as ChangeType);
            resetPlan();
          }}
        >
          <option value="interface_description">Interface description</option>
          <option value="interface_admin_state">Interface admin state</option>
        </SelectField>
        <SelectField
          label="Interface"
          value={target}
          onChange={(event) => {
            setTarget(event.target.value);
            resetPlan();
          }}
        >
          <option value="">Select an interface</option>
          {(interfaces.data ?? []).map((iface) => (
            <option key={iface.id} value={iface.name}>
              {iface.name}
            </option>
          ))}
        </SelectField>
        {changeType === 'interface_admin_state' ? (
          <SelectField
            label="Desired admin state"
            value={desiredValue}
            onChange={(event) => {
              setDesiredValue(event.target.value);
              resetPlan();
            }}
          >
            <option value="">Select</option>
            <option value="up">up</option>
            <option value="down">down</option>
          </SelectField>
        ) : (
          <InputField
            label="New description"
            value={desiredValue}
            onChange={(event) => {
              setDesiredValue(event.target.value);
              resetPlan();
            }}
            placeholder="uplink-to-lab-core"
          />
        )}
        <Button
          size="small"
          onClick={() => preview.mutate()}
          busy={preview.isPending}
          disabled={target === '' || desiredValue === ''}
        >
          <Settings2 size={14} /> Preview
        </Button>
      </div>
      {preview.error === null ? null : (
        <div className="form-error" role="alert">
          {preview.error.message}
        </div>
      )}
      {plan === null ? null : (
        <div className="configure-preview">
          <div>
            <Badge tone={plan.risk === 'high' ? 'danger' : 'success'}>{plan.risk} risk</Badge>
            <Badge tone="neutral">Safety level {plan.safety_level} · best effort</Badge>
          </div>
          {plan.steps.map((step) => (
            <div key={step.id} className="configure-preview__step">
              <p>
                {step.target}: <span className="mono">{step.previous_value ?? '(none)'}</span> →{' '}
                <span className="mono">{step.desired_value}</span>
              </p>
              <pre>{step.rendered_commands}</pre>
            </div>
          ))}
          <Button
            variant="primary"
            size="small"
            onClick={() => apply.mutate(plan.id)}
            busy={apply.isPending}
            disabled={plan.status !== 'draft'}
          >
            <ShieldCheck size={14} /> Apply
          </Button>
          {apply.error === null ? null : (
            <div className="form-error" role="alert">
              {apply.error.message}
            </div>
          )}
          {apply.isSuccess ? (
            <div className="mini-result mini-result--success" role="status">
              <Check size={14} />
              <span>Apply queued. The status below updates when the worker finishes.</span>
            </div>
          ) : null}
        </div>
      )}
      {history.data?.some((item) => item.status === 'rollback_failed') === true ? (
        <InlineNotice tone="danger" title="A rollback did not complete">
          One of the changes below applied, failed its post-check, and could not be reversed. The
          device is in an unknown state for that interface — verify it directly before making
          another change.
        </InlineNotice>
      ) : null}
      <div>
        <strong>Past changes</strong>
        {history.data === undefined || history.data.length === 0 ? (
          <AppState
            kind="empty"
            title="No changes yet"
            message="Preview and apply a change to see its history here."
            compact
          />
        ) : (
          <div className="snapshot-list">
            {history.data.map((item) => (
              <div key={item.id} className="configure-history__item">
                <Badge tone={changePlanStatusTone[item.status]}>{item.status}</Badge>
                <span>{item.steps[0]?.target}</span>
                {item.failure_code === null ? null : <small className="mono">{item.failure_code}</small>}
                <small>{formatDateTime(item.created_at)}</small>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ActivityTab({ device }: { device: Device }) {
  const events = useQuery({
    queryKey: ['events', { deviceId: device.id }],
    queryFn: () => api.events(device.id, 50),
    retry: false,
  });
  if (events.isPending) {
    return <AppState kind="loading" title="Loading activity" message="Reading the sanitized event log…" />;
  }
  if (events.isError) {
    return <QueryErrorState error={events.error} onRetry={() => void events.refetch()} />;
  }
  return <EventTimeline events={events.data} compact />;
}

export function DeviceInspector({ device, onClose, onEdit, onDelete }: DeviceInspectorProps) {
  const [tab, setTab] = useState<InspectorTab>('overview');
  const [activeJob, setActiveJob] = useState<{ id: string; label: string }>();
  const queryClient = useQueryClient();
  const refresh = useMutation({
    mutationFn: (target: Device) => api.refreshDevice(target.id),
    onSuccess: (job: Job) => setActiveJob({ id: job.id, label: 'Refreshing observed state' }),
  });
  const capture = useMutation({
    mutationFn: (target: Device) => api.captureSnapshot(target.id),
    onSuccess: (job: Job) => setActiveJob({ id: job.id, label: 'Capturing running configuration' }),
  });
  // Virtual lab nodes regenerate their SSH host key on every restart, which
  // otherwise blocks every operation until the device is deleted and re-added.
  const repin = useMutation({
    mutationFn: async (target: Device) => {
      const candidate = await api.collectHostKeyCandidate({
        name: target.name,
        management_address: target.management_address,
        port: target.port,
        vendor: target.vendor,
        credential_profile_id: target.credential_profile_id,
        ssh_compatibility: target.ssh_compatibility ?? 'modern',
        is_lab: target.is_lab,
        console_transport: target.console_transport,
        group1_risk_acknowledged: target.ssh_compatibility === 'cisco_legacy_group1',
        very_old_risk_acknowledged: target.ssh_compatibility === 'very_old_ssh',
      });
      return api.repinHostKey(target.id, candidate.id);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['devices'] });
    },
  });
  const diagnostic = useMutation({
    mutationFn: ({ device: target, action, destination }: {
      device: Device;
      action: DiagnosticAction;
      destination?: string;
    }) => api.runDiagnostic(target.id, action, destination),
    onSuccess: (queued: Job) =>
      setActiveJob({ id: queued.id, label: 'Running allowlisted diagnostic' }),
  });
  const job = useQuery({
    queryKey: ['jobs', activeJob?.id],
    queryFn: () => api.job(activeJob?.id ?? ''),
    enabled: activeJob !== undefined,
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.state;
      return status !== undefined && finalJobStates.has(status) ? false : 1_000;
    },
  });

  useEffect(() => {
    if (device === null || job.data === undefined || !finalJobStates.has(job.data.state)) return;
    if (job.data.state === 'succeeded') {
      void queryClient.invalidateQueries({ queryKey: ['devices'] });
      void queryClient.invalidateQueries({ queryKey: ['devices', device.id] });
      void queryClient.invalidateQueries({ queryKey: ['snapshots', { deviceId: device.id }] });
      void queryClient.invalidateQueries({ queryKey: ['events'] });
    }
  }, [device, job.data, queryClient]);

  const tabs = useMemo(
    () => [
      { id: 'overview' as const, label: 'Overview', icon: CircleGauge },
      { id: 'interfaces' as const, label: 'Interfaces', icon: Network },
      { id: 'neighbors' as const, label: 'Neighbors', icon: Waypoints },
      { id: 'diagnostics' as const, label: 'Diagnostics', icon: ListTree },
      { id: 'terminal' as const, label: 'Terminal', icon: SquareTerminal },
      { id: 'snapshots' as const, label: 'Snapshots', icon: FileLock2 },
      { id: 'configure' as const, label: 'Configure', icon: Settings2 },
      { id: 'activity' as const, label: 'Activity', icon: Activity },
    ],
    [],
  );

  if (device === null) {
    // No collapse control here: collapsing this placeholder reclaims no
    // useful space, and with nothing selected the only way back is
    // selectDevice() in InventoryPage -- picking a device. An empty
    // inventory would make that dead-end unrecoverable.
    return (
      <aside className="inspector inspector--empty" aria-label="Device inspector">
        <AppState
          kind="empty"
          title="Select a device"
          message="Choose a device from inventory to inspect facts, interfaces, snapshots, and sanitized activity."
        />
      </aside>
    );
  }

  const jobRunning =
    activeJob !== undefined && (job.data === undefined || !finalJobStates.has(job.data.state));
  const jobFailed = job.data?.state === 'failed';

  return (
    <aside className={tab === 'terminal' ? 'inspector inspector--terminal' : 'inspector'} aria-label={`${device.name} inspector`}>
      <header className="inspector__header">
        <div className="device-avatar" aria-hidden="true">
          <Router size={21} />
        </div>
        <div className="inspector__identity">
          <span>DEVICE INSPECTOR</span>
          <h2>{device.name}</h2>
          <div>
            <Badge tone={stateTone(device.status)} dot>
              {device.status}
            </Badge>
            {device.ssh_compatibility === 'cisco_legacy' ||
            device.ssh_compatibility === 'cisco_legacy_group1' ||
            device.ssh_compatibility === 'very_old_ssh' ? (
              <Badge tone="warning">LEGACY SSH</Badge>
            ) : null}
            {device.is_lab ? <Badge tone="purple">LAB</Badge> : null}
            {device.console_transport === 'telnet' ? (
              <Badge tone="danger">TELNET · CLEARTEXT</Badge>
            ) : null}
            <span className="mono">{device.management_address}</span>
          </div>
        </div>
        <button type="button" className="icon-button inspector__close" onClick={onClose} aria-label="Close inspector">
          <X size={18} />
        </button>
      </header>
      <div className="inspector__actions">
        <Button size="small" onClick={() => refresh.mutate(device)} busy={refresh.isPending || jobRunning}>
          <RefreshCw size={14} /> Refresh observed state
        </Button>
        <Button size="small" variant="ghost" onClick={() => onEdit(device)}>
          <Pencil size={14} /> Edit
        </Button>
        {device.is_lab ? (
          <Button
            size="small"
            variant="ghost"
            onClick={() => repin.mutate(device)}
            busy={repin.isPending}
            title="Re-inspect and pin the host key this lab node presents now"
          >
            <KeyRound size={14} /> Re-pin host key
          </Button>
        ) : null}
        <Button size="small" variant="ghost" className="button--icon-only" onClick={() => onDelete(device)} aria-label="Delete device">
          <Trash2 size={14} />
        </Button>
      </div>
      {repin.isError ? <ConnectionError error={repin.error} fallback="Re-pinning failed." /> : null}
      {repin.isSuccess ? (
        <InlineNotice tone="safe" title="Host key re-pinned">
          The key this lab node presents now is the one Terraformer will trust.
        </InlineNotice>
      ) : null}
      {activeJob === undefined ? null : (
        <div
          className={`job-banner ${jobFailed ? 'job-banner--error' : ''}`}
          role={jobFailed ? 'alert' : 'status'}
        >
          {jobRunning ? (
            <LoaderCircle className="spin" size={15} />
          ) : jobFailed ? (
            <CircleX size={15} />
          ) : (
            <Check size={15} />
          )}
          <span>
            {activeJob.label}
            {job.data === undefined ? '…' : ` · ${job.data.state}`}
          </span>
        </div>
      )}
      <nav className="inspector-tabs" aria-label="Inspector sections">
        {tabs.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? 'is-active' : ''}
              onClick={() => setTab(item.id)}
              aria-current={tab === item.id ? 'page' : undefined}
            >
              <Icon size={15} /> {item.label}
            </button>
          );
        })}
      </nav>
      <div className="inspector__content">
        {tab === 'overview' ? <OverviewTab device={device} /> : null}
        {tab === 'interfaces' ? <InterfacesTab device={device} /> : null}
        {tab === 'neighbors' ? <NeighborsTab device={device} /> : null}
        {tab === 'diagnostics' ? (
          <DiagnosticsTab
            device={device}
            job={job.data}
            running={diagnostic.isPending || jobRunning}
            error={diagnostic.error?.message}
            onRun={(action, destination) =>
              diagnostic.mutate({
                device,
                action,
                ...(destination === undefined ? {} : { destination }),
              })
            }
          />
        ) : null}
        {tab === 'terminal' ? (
          <Suspense fallback={<AppState kind="loading" title="Loading terminal" message="Preparing the local PTY client…" compact />}>
            <TerminalPanel
              deviceId={device.id}
              sshCompatibility={device.ssh_compatibility ?? 'modern'}
              consoleTransport={device.console_transport}
            />
          </Suspense>
        ) : null}
        {tab === 'snapshots' ? (
          <SnapshotsTab
            device={device}
            onCapture={() => capture.mutate(device)}
            capturing={capture.isPending || jobRunning}
          />
        ) : null}
        {tab === 'configure' ? <ConfigureTab device={device} /> : null}
        {tab === 'activity' ? <ActivityTab device={device} /> : null}
      </div>
      <footer className="inspector__footer">
        <ShieldCheck size={14} /> Structured writes require explicit preview and apply · Terminal is Direct Mode
      </footer>
    </aside>
  );
}
