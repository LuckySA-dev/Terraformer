import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Cable,
  CheckCircle2,
  Filter,
  KeyRound,
  MoreHorizontal,
  Plus,
  Radar,
  Router,
  Search,
  ShieldCheck,
  Unplug,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { api } from '../../api/network';
import type { CredentialProfileInput, Device, DeviceInput, DiscoveryCandidate } from '../../types/api';
import { AppState, QueryErrorState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import { formatRelativeTime } from '../../lib/format';
import { CredentialForm } from './CredentialForm';
import { DeviceForm } from './DeviceForm';
import { DeviceInspector } from './DeviceInspector';
import { DiscoveryDialog } from './DiscoveryDialog';
import { UsbConsoleDialog } from './UsbConsoleDialog';

type DeviceDialog =
  | { mode: 'create' }
  | { mode: 'edit'; device: Device }
  | { mode: 'approve'; jobId: string; candidate: DiscoveryCandidate }
  | null;

function deviceTone(status: string): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'reachable') return 'success';
  if (status === 'unreachable') return 'danger';
  return 'warning';
}

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: typeof Router;
  label: string;
  value: string;
  detail: string;
  tone: 'blue' | 'green' | 'red' | 'violet';
}) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__icon">
        <Icon size={18} />
      </div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function InventoryTable({
  devices,
  selectedId,
  onSelect,
}: {
  devices: Device[];
  selectedId: string | undefined;
  onSelect: (device: Device) => void;
}) {
  return (
    <div className="device-table-wrap">
      <table className="device-table">
        <thead>
          <tr>
            <th>Device</th>
            <th>Management</th>
            <th>Platform</th>
            <th>State</th>
            <th>Last observed</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {devices.map((device) => (
            <tr key={device.id} className={device.id === selectedId ? 'is-selected' : ''}>
              <td>
                <button className="device-name" type="button" onClick={() => onSelect(device)}>
                  <span className="device-name__icon">
                    <Router size={17} />
                  </span>
                  <span>
                    <strong>{device.name}</strong>
                    <small>{device.facts.hostname ?? 'Hostname not observed'}</small>
                  </span>
                </button>
              </td>
              <td>
                <span className="mono table-primary">{device.management_address}</span>
                <small className="table-secondary">SSH · {device.port}</small>
              </td>
              <td>
                <span className="table-primary">{device.vendor === 'generic' ? 'Generic · test only' : device.vendor === 'fortinet_fortios' ? 'Fortinet FortiOS · test only' : 'Cisco IOS / IOS-XE'}</span>
                <small className="table-secondary">{device.facts.model ?? 'Model unavailable'}</small>
                {device.ssh_compatibility === 'cisco_legacy' ||
                device.ssh_compatibility === 'cisco_legacy_group1' ||
                device.ssh_compatibility === 'very_old_ssh' ? (
                  <Badge tone="warning">LEGACY SSH</Badge>
                ) : null}
              </td>
              <td>
                <Badge tone={deviceTone(device.status)} dot>
                  {device.status}
                </Badge>
              </td>
              <td>
                <span className="table-primary">{formatRelativeTime(device.last_seen_at)}</span>
                <small className="table-secondary">Observed state</small>
              </td>
              <td>
                <button className="icon-button" type="button" onClick={() => onSelect(device)} aria-label={`Inspect ${device.name}`}>
                  <MoreHorizontal size={17} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function InventoryPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string>();
  const [deviceDialog, setDeviceDialog] = useState<DeviceDialog>(null);
  const [credentialOpen, setCredentialOpen] = useState(false);
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const [usbConsoleOpen, setUsbConsoleOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Device>();

  const devices = useQuery({ queryKey: ['devices'], queryFn: api.devices, retry: false });
  const credentials = useQuery({
    queryKey: ['credential-profiles'],
    queryFn: api.credentialProfiles,
    retry: false,
  });
  const saveDevice = useMutation({
    mutationFn: ({ input, current, discoveryJobId }: { input: DeviceInput; current?: Device; discoveryJobId?: string }) =>
      current !== undefined
        ? api.updateDevice(current.id, input)
        : discoveryJobId !== undefined
          ? api.approveDiscoveryCandidate(discoveryJobId, input)
          : api.createDevice(input),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: ['devices'] });
      setSelectedId(saved.id);
      setDeviceDialog(null);
    },
  });
  const createCredential = useMutation({
    mutationFn: (input: CredentialProfileInput) => api.createCredentialProfile(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['credential-profiles'] });
      setCredentialOpen(false);
    },
  });
  const deleteDevice = useMutation({
    mutationFn: (device: Device) => api.deleteDevice(device.id),
    onSuccess: async (_data, deleted) => {
      if (selectedId === deleted.id) setSelectedId(undefined);
      setDeleteTarget(undefined);
      await queryClient.invalidateQueries({ queryKey: ['devices'] });
      await queryClient.invalidateQueries({ queryKey: ['events'] });
    },
  });

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (term.length === 0) return devices.data ?? [];
    return (devices.data ?? []).filter((device) =>
      [device.name, device.management_address, device.facts.hostname, device.facts.model]
        .filter((value): value is string => value !== undefined && value !== null)
        .some((value) => value.toLowerCase().includes(term)),
    );
  }, [devices.data, search]);

  const selectedDevice = devices.data?.find((device) => device.id === selectedId) ?? null;
  const reachable = (devices.data ?? []).filter(
    (device) => device.status === 'reachable',
  ).length;
  const unreachable = (devices.data ?? []).filter(
    (device) =>
      device.status === 'unreachable',
  ).length;

  return (
    <div className="workspace-layout">
      <main className="workspace-main">
        <header className="page-header">
          <div>
            <span className="eyebrow">PHASE 2 · SAFE DISCOVERY</span>
            <h1>Device inventory</h1>
            <p>Structured connections remain read-only; manual terminals are Direct Mode.</p>
          </div>
          <div className="page-header__actions">
            <Button onClick={() => setUsbConsoleOpen(true)}>
              <Cable size={16} /> Open USB Console
            </Button>
            <Button onClick={() => setDiscoveryOpen(true)}>
              <Radar size={16} /> Discover
            </Button>
            <Button onClick={() => setCredentialOpen(true)}>
              <KeyRound size={16} /> Credential profile
            </Button>
            <Button variant="primary" onClick={() => setDeviceDialog({ mode: 'create' })}>
              <Plus size={16} /> Add device
            </Button>
          </div>
        </header>

        <section className="metrics-grid" aria-label="Inventory summary">
          <MetricCard
            icon={Box}
            label="Registered"
            value={String(devices.data?.length ?? 0)}
            detail="of 50 initial capacity"
            tone="blue"
          />
          <MetricCard icon={CheckCircle2} label="Reachable" value={String(reachable)} detail="last explicit check" tone="green" />
          <MetricCard icon={Unplug} label="Disconnected" value={String(unreachable)} detail="requires attention" tone="red" />
          <MetricCard icon={ShieldCheck} label="Structured writes" value="Blocked" detail="Manual terminals bypass automation" tone="violet" />
        </section>

        <section className="inventory-panel" aria-labelledby="inventory-heading">
          <div className="inventory-toolbar">
            <div>
              <h2 id="inventory-heading">All devices</h2>
              <Badge tone="neutral">{filtered.length} shown</Badge>
            </div>
            <div className="inventory-toolbar__tools">
              <label className="search-box">
                <Search size={16} aria-hidden="true" />
                <span className="sr-only">Search devices</span>
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search name, IP, model…"
                />
              </label>
              <button className="icon-button icon-button--bordered" type="button" aria-label="Filters are not active" disabled>
                <Filter size={16} />
              </button>
            </div>
          </div>
          {devices.isPending ? (
            <AppState kind="loading" title="Loading inventory" message="Reading registered devices from the local API…" />
          ) : devices.isError ? (
            <QueryErrorState error={devices.error} onRetry={() => void devices.refetch()} />
          ) : devices.data.length === 0 ? (
            <AppState
              kind="empty"
              title="Your inventory is empty"
              message="Add a Cisco IOS or IOS-XE device. Terraformer will not connect until you explicitly run a connection test."
              actionLabel="Add first device"
              onAction={() => setDeviceDialog({ mode: 'create' })}
              accessory={<Cable size={24} aria-hidden="true" />}
            />
          ) : filtered.length === 0 ? (
            <AppState kind="empty" title="No matching devices" message="Try a different name, IP address, hostname, or model." />
          ) : (
            <InventoryTable devices={filtered} selectedId={selectedId} onSelect={(device) => setSelectedId(device.id)} />
          )}
        </section>
      </main>

      <DeviceInspector
        key={selectedDevice?.id ?? 'empty'}
        device={selectedDevice}
        onClose={() => setSelectedId(undefined)}
        onEdit={(device) => setDeviceDialog({ mode: 'edit', device })}
        onDelete={setDeleteTarget}
      />

      <Modal
        open={usbConsoleOpen}
        title="Manual USB Console"
        description="Browser-local USB Direct Mode. No device record or backend connection is required."
        onClose={() => setUsbConsoleOpen(false)}
        size="large"
      >
        <UsbConsoleDialog />
      </Modal>

      <Modal
        open={deviceDialog !== null}
        title={deviceDialog?.mode === 'edit' ? 'Edit device' : 'Add a Cisco device'}
        description="Saving requires a successful, explicit read-only connection test."
        onClose={() => setDeviceDialog(null)}
        size="large"
      >
        {credentials.isPending ? (
          <AppState kind="loading" title="Loading credentials" message="Reading credential profile metadata…" compact />
        ) : credentials.isError ? (
          <QueryErrorState error={credentials.error} onRetry={() => void credentials.refetch()} compact />
        ) : (
          <DeviceForm
            {...(deviceDialog?.mode === 'edit' ? { device: deviceDialog.device } : {})}
            {...(deviceDialog?.mode === 'approve'
              ? {
                  initial: {
                    management_address: deviceDialog.candidate.management_address,
                    port: deviceDialog.candidate.port,
                  },
                }
              : {})}
            credentials={credentials.data}
            onCancel={() => setDeviceDialog(null)}
            onCreateCredential={() => setCredentialOpen(true)}
            onSubmit={async (input) => {
              await saveDevice.mutateAsync({
                input,
                ...(deviceDialog?.mode === 'edit' ? { current: deviceDialog.device } : {}),
                ...(deviceDialog?.mode === 'approve' ? { discoveryJobId: deviceDialog.jobId } : {}),
              });
            }}
            error={saveDevice.error?.message}
          />
        )}
      </Modal>

      <Modal
        open={discoveryOpen}
        title="Discover SSH candidates"
        description="A bounded port probe only. Every candidate requires review and a successful connection test."
        onClose={() => setDiscoveryOpen(false)}
        size="large"
      >
        <DiscoveryDialog
          onApprove={(jobId, candidate) => {
            setDiscoveryOpen(false);
            setDeviceDialog({ mode: 'approve', jobId, candidate });
          }}
        />
      </Modal>

      <Modal
        open={credentialOpen}
        title="New credential profile"
        description="Create an encrypted, reusable profile without attaching secrets to a device record."
        onClose={() => setCredentialOpen(false)}
      >
        <CredentialForm
          onCancel={() => setCredentialOpen(false)}
          onSubmit={(input) => createCredential.mutateAsync(input).then(() => undefined)}
          error={createCredential.error?.message}
        />
      </Modal>

      <Modal
        open={deleteTarget !== undefined}
        title="Remove device from inventory?"
        description="This removes the inventory record. It does not connect to or change the network device."
        onClose={() => setDeleteTarget(undefined)}
        size="small"
        footer={
          <>
            <Button onClick={() => setDeleteTarget(undefined)}>Cancel</Button>
            <Button
              variant="danger"
              busy={deleteDevice.isPending}
              onClick={() => {
                if (deleteTarget !== undefined) deleteDevice.mutate(deleteTarget);
              }}
            >
              Remove device
            </Button>
          </>
        }
      >
        <div className="delete-summary">
          <div className="device-avatar">
            <Router size={20} />
          </div>
          <div>
            <strong>{deleteTarget?.name}</strong>
            <span className="mono">{deleteTarget?.management_address}</span>
          </div>
        </div>
        {deleteDevice.error === null ? null : (
          <div className="form-error" role="alert">
            {deleteDevice.error.message}
          </div>
        )}
      </Modal>
    </div>
  );
}
