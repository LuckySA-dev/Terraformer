import { useQueries, useQuery } from '@tanstack/react-query';
import cytoscape from 'cytoscape';
import type { StylesheetJson } from 'cytoscape';
import { Network, RefreshCw, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/network';
import { AppState, QueryErrorState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import {
  buildTopologyElements,
  loadManualTopologyLinks,
  loadTopologyPositions,
  TOPOLOGY_MANUAL_LINKS_KEY,
  TOPOLOGY_POSITIONS_KEY,
} from './topology';
import type { TopologyElement } from './topology';

const topologyStyle: StylesheetJson = [
  {
    selector: 'node',
    style: {
      label: 'data(label)',
      'background-color': '#71817d',
      'border-color': '#ffffff',
      'border-width': 3,
      color: '#24312f',
      'font-size': 10,
      'font-weight': 700,
      'text-background-color': '#ffffff',
      'text-background-opacity': 0.9,
      'text-background-padding': '3px',
      'text-margin-y': 10,
      'text-valign': 'bottom',
      height: 34,
      width: 34,
    },
  },
  {
    selector: 'node[kind = "registered"]',
    style: {
      'background-color': '#196b5b',
      height: 42,
      width: 42,
    },
  },
  {
    selector: 'node[status = "unreachable"]',
    style: { 'background-color': '#ba4650' },
  },
  {
    selector: 'node[kind = "observed"]',
    style: {
      'background-color': '#ffffff',
      'border-color': '#7c8d89',
      'border-style': 'dashed',
      'border-width': 2,
    },
  },
  {
    selector: 'edge',
    style: {
      label: 'data(label)',
      width: 2,
      'line-color': '#8fa6a0',
      'target-arrow-color': '#8fa6a0',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      color: '#556762',
      'font-size': 8,
      'text-background-color': '#f7faf9',
      'text-background-opacity': 1,
      'text-background-padding': '2px',
    },
  },
  {
    selector: 'edge[protocol = "lldp"]',
    style: {
      'line-color': '#7180b9',
      'target-arrow-color': '#7180b9',
    },
  },
  {
    selector: 'edge[protocol = "manual"]',
    style: {
      'line-color': '#b17b24',
      'line-style': 'dashed',
      'target-arrow-color': '#b17b24',
    },
  },
];

function TopologyCanvas({ elements }: { elements: TopologyElement[] }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (container.current === null) return undefined;
    const graph = cytoscape({
      container: container.current,
      elements,
      style: topologyStyle,
      layout: {
        name: elements.every(
          (element) => element.group === 'edges' || element.position !== undefined,
        )
          ? 'preset'
          : 'cose',
        animate: false,
        fit: true,
        padding: 35,
      },
      boxSelectionEnabled: false,
      minZoom: 0.35,
      maxZoom: 2.5,
    });
    graph.on('dragfree', 'node', () => {
      const positions = Object.fromEntries(
        graph.nodes().map((node) => [node.id(), node.position()]),
      );
      localStorage.setItem(TOPOLOGY_POSITIONS_KEY, JSON.stringify(positions));
    });
    return () => graph.destroy();
  }, [elements]);

  return (
    <div
      ref={container}
      className="topology-canvas"
      role="img"
      aria-label="Read-only topology of registered devices and observed neighbors"
    />
  );
}

export function TopologyPage() {
  const [layoutRevision, setLayoutRevision] = useState(0);
  const [refreshSeconds, setRefreshSeconds] = useState(0);
  const [manualLinks, setManualLinks] = useState(() => loadManualTopologyLinks(localStorage));
  const [manualSource, setManualSource] = useState('');
  const [manualTarget, setManualTarget] = useState('');
  const refreshInterval = refreshSeconds === 0 ? false : refreshSeconds * 1_000;
  const devices = useQuery({
    queryKey: ['devices'],
    queryFn: api.devices,
    retry: false,
    refetchInterval: refreshInterval,
  });
  const neighborQueries = useQueries({
    queries: (devices.data ?? []).map((device) => ({
      queryKey: ['devices', device.id, 'neighbors'],
      queryFn: () => api.neighbors(device.id),
      retry: false,
      refetchInterval: refreshInterval,
    })),
  });
  const neighborError = neighborQueries.find((query) => query.isError && query.data === undefined);
  const staleError =
    (devices.isError && devices.data !== undefined) ||
    neighborQueries.some((query) => query.isError && query.data !== undefined);
  const pending = devices.isPending || neighborQueries.some((query) => query.isPending);
  const refreshing = devices.isFetching || neighborQueries.some((query) => query.isFetching);

  if (devices.isError && devices.data === undefined) {
    return <QueryErrorState error={devices.error} onRetry={() => void devices.refetch()} />;
  }
  if (neighborError !== undefined) {
    return (
      <QueryErrorState
        error={neighborError.error}
        onRetry={() => void Promise.all(neighborQueries.map((query) => query.refetch()))}
      />
    );
  }
  if (pending) {
    return (
      <AppState
        kind="loading"
        title="Building topology"
        message="Reading saved inventory and observed neighbor records..."
      />
    );
  }
  if (devices.data.length === 0) {
    return (
      <AppState
        kind="empty"
        title="No topology yet"
        message="Register a device and run an explicit refresh to collect observed links."
        accessory={<Network size={24} aria-hidden="true" />}
      />
    );
  }

  const neighborGroups = devices.data.map((device, index) => ({
    deviceId: device.id,
    neighbors: neighborQueries[index]?.data ?? [],
  }));
  const positions = loadTopologyPositions(localStorage);
  const elements = buildTopologyElements(devices.data, neighborGroups, positions, manualLinks);
  const nodeCount = elements.filter((element) => element.group === 'nodes').length;
  const linkCount = elements.filter((element) => element.group === 'edges').length;
  const saveManualLinks = (links: typeof manualLinks) => {
    setManualLinks(links);
    localStorage.setItem(TOPOLOGY_MANUAL_LINKS_KEY, JSON.stringify(links));
  };

  return (
    <main className="topology-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">PHASE 2 / OBSERVED TOPOLOGY</span>
          <h1>Network topology</h1>
          <p>Read-only projection from registered inventory and saved CDP/LLDP evidence.</p>
        </div>
        <Badge tone="success">NO DEVICE WRITES</Badge>
      </header>
      <section className="topology-panel" aria-labelledby="topology-heading">
        {staleError ? (
          <div className="topology-stale-alert" role="alert">
            <span>Refresh failed. Showing last observed topology.</span>
            <Button
              size="small"
              onClick={() => {
                void devices.refetch();
                void Promise.all(neighborQueries.map((query) => query.refetch()));
              }}
            >
              Retry
            </Button>
          </div>
        ) : null}
        <div className="topology-toolbar">
          <div>
            <h2 id="topology-heading">Observed graph</h2>
            <span>{nodeCount} nodes / {linkCount} links</span>
          </div>
          <div className="topology-tools">
            <div className="topology-legend" aria-label="Topology legend">
              <span><i className="topology-dot topology-dot--registered" /> Registered</span>
              <span><i className="topology-dot topology-dot--observed" /> Observed only</span>
              <span><i className="topology-line topology-line--manual" /> Unverified link</span>
            </div>
            <label className="topology-refresh-interval">
              Refresh
              <select
                value={refreshSeconds}
                onChange={(event) => setRefreshSeconds(Number(event.target.value))}
              >
                <option value={0}>Manual</option>
                <option value={30}>30 sec</option>
                <option value={60}>60 sec</option>
              </select>
            </label>
            <Button
              size="small"
              busy={refreshing}
              onClick={() => {
                void devices.refetch();
                void Promise.all(neighborQueries.map((query) => query.refetch()));
              }}
            >
              <RefreshCw size={13} /> Refresh view
            </Button>
            <Button
              size="small"
              onClick={() => {
                localStorage.removeItem(TOPOLOGY_POSITIONS_KEY);
                setLayoutRevision(layoutRevision + 1);
              }}
            >
              Reset layout
            </Button>
          </div>
        </div>
        <div className="topology-manual-links">
          <strong>Manual evidence</strong>
          <select aria-label="Manual link source" value={manualSource} onChange={(event) => setManualSource(event.target.value)}>
            <option value="">Source device</option>
            {devices.data.map((device) => <option key={device.id} value={device.id}>{device.name}</option>)}
          </select>
          <select aria-label="Manual link target" value={manualTarget} onChange={(event) => setManualTarget(event.target.value)}>
            <option value="">Target device</option>
            {devices.data.map((device) => <option key={device.id} value={device.id}>{device.name}</option>)}
          </select>
          <Button
            size="small"
            disabled={!manualSource || !manualTarget || manualSource === manualTarget}
            onClick={() => {
              saveManualLinks([
                ...manualLinks,
                { id: crypto.randomUUID(), sourceDeviceId: manualSource, targetDeviceId: manualTarget },
              ]);
              setManualSource('');
              setManualTarget('');
            }}
          >
            Add unverified link
          </Button>
          {manualLinks.map((link) => (
            <Button
              key={link.id}
              size="small"
              variant="ghost"
              aria-label="Remove unverified link"
              onClick={() => saveManualLinks(manualLinks.filter((item) => item.id !== link.id))}
            >
              <Trash2 size={12} /> UNVERIFIED
            </Button>
          ))}
        </div>
        <TopologyCanvas elements={elements} />
        <p className="topology-note">
          Drag nodes to save positions in this browser. Observed nodes remain evidence, not inventory records.
          Manual links stay local and are always labeled UNVERIFIED.
        </p>
      </section>
    </main>
  );
}

export default TopologyPage;
