import { useQueries, useQuery } from '@tanstack/react-query';
import cytoscape from 'cytoscape';
import type { LayoutOptions, PresetLayoutOptions, StylesheetJson } from 'cytoscape';
import fcose from 'cytoscape-fcose';
import type { FcoseLayoutOptions } from 'cytoscape-fcose';
import { Network, RefreshCw, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/network';
import { AppState, QueryErrorState } from '../../components/ui/AppState';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { DeviceInspector } from '../inventory/DeviceInspector';
import {
  buildTopologyElements,
  loadManualTopologyLinks,
  loadTopologyPositions,
  TOPOLOGY_MANUAL_LINKS_KEY,
  TOPOLOGY_POSITIONS_KEY,
} from './topology';
import type { TopologyElement } from './topology';

cytoscape.use(fcose);

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
      'text-wrap': 'wrap',
      'text-max-width': '80px',
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
    selector: 'node.is-selected',
    style: {
      'border-color': '#b17b24',
      'border-width': 5,
      'font-size': 12,
      'z-index': 20,
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
      'text-rotation': 'autorotate',
      // Drop link labels once they would render too small to read, so a
      // zoomed-out view shows topology shape instead of a wall of text.
      'min-zoomed-font-size': 7,
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

// Identity of the graph's *content*, ignoring array identity and saved
// positions. The build effect keys off this so unrelated re-renders — a node
// tap, a refresh poll, a filter toggle that changes nothing — never destroy
// and re-lay-out the graph under the operator.
function graphSignature(elements: TopologyElement[]): string {
  return elements
    .map((element) =>
      element.group === 'nodes'
        ? `n:${element.data.id}:${element.data.label}:${element.data.kind}:${element.data.status}`
        : `e:${element.data.id}:${element.data.source}:${element.data.target}:${element.data.label}`,
    )
    .join('|');
}

function TopologyCanvas({
  elements,
  onNodeTap,
  selectedDeviceId,
}: {
  elements: TopologyElement[];
  onNodeTap?: (deviceId: string) => void;
  selectedDeviceId?: string | undefined;
}) {
  const container = useRef<HTMLDivElement>(null);
  const graphRef = useRef<cytoscape.Core>(null);
  // A ref, not an effect dependency: onNodeTap is a fresh closure on every
  // parent render (e.g. the refresh-interval poll), and rebuilding the whole
  // cytoscape instance for that would lose in-progress drag state and
  // re-trigger the layout for no reason.
  const onNodeTapRef = useRef(onNodeTap);
  useEffect(() => {
    onNodeTapRef.current = onNodeTap;
  }, [onNodeTap]);
  const elementsRef = useRef(elements);
  useEffect(() => {
    elementsRef.current = elements;
  }, [elements]);
  const signature = graphSignature(elements);

  useEffect(() => {
    if (container.current === null) return undefined;
    const elements = elementsRef.current;
    const hasSavedPositions = elements.every(
      (element) => element.group === 'edges' || element.position !== undefined,
    );
    const layout: FcoseLayoutOptions | PresetLayoutOptions = hasSavedPositions
      ? { name: 'preset', animate: false, fit: true, padding: 35 }
      : {
          name: 'fcose',
          animate: false,
          fit: true,
          padding: 35,
          // "proof" quality is required for nodeDimensionsIncludeLabels to take
          // effect — it's what actually keeps labels from overlapping.
          quality: 'proof',
          nodeDimensionsIncludeLabels: true,
          nodeSeparation: 90,
          idealEdgeLength: 100,
        };
    const graph = cytoscape({
      container: container.current,
      elements,
      style: topologyStyle,
      // cytoscape-fcose's own option type doesn't line up byte-for-byte with
      // cytoscape core's LayoutOptions union under exactOptionalPropertyTypes,
      // even though the shape fcose actually expects at runtime is correct.
      layout: layout as LayoutOptions,
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
    graph.on('tap', 'node', (event: cytoscape.EventObjectNode) => {
      const id = event.target.id();
      if (id.startsWith('device:')) onNodeTapRef.current?.(id.slice('device:'.length));
    });
    graphRef.current = graph;
    return () => {
      graphRef.current = null;
      graph.destroy();
    };
  }, [signature]);

  // Selection is a style change, not a rebuild — highlighting the tapped node
  // must never disturb the layout the operator is looking at.
  useEffect(() => {
    const graph = graphRef.current;
    if (graph === null) return;
    graph.nodes('.is-selected').removeClass('is-selected');
    if (selectedDeviceId !== undefined) {
      graph.getElementById(`device:${selectedDeviceId}`).addClass('is-selected');
    }
  }, [selectedDeviceId, signature]);

  return (
    <div
      ref={container}
      className="topology-canvas"
      role="img"
      aria-label="Read-only topology of registered devices and observed neighbors"
    />
  );
}

interface TopologyPageProps {
  onFocusDevice?: (deviceId: string) => void;
}

export function TopologyPage({ onFocusDevice }: TopologyPageProps) {
  const [layoutRevision, setLayoutRevision] = useState(0);
  const [refreshSeconds, setRefreshSeconds] = useState(0);
  const [manualLinks, setManualLinks] = useState(() => loadManualTopologyLinks(localStorage));
  const [manualSource, setManualSource] = useState('');
  const [manualTarget, setManualTarget] = useState('');
  const [showCdp, setShowCdp] = useState(true);
  const [showLldp, setShowLldp] = useState(true);
  const [registeredOnly, setRegisteredOnly] = useState(false);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>();
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
  const filteredEdges = elements.filter(
    (element): element is Extract<TopologyElement, { group: 'edges' }> =>
      element.group === 'edges'
      && (element.data.protocol === 'manual' ? true : element.data.protocol === 'cdp' ? showCdp : showLldp)
      && (!registeredOnly
        || (!element.data.source.startsWith('observed:') && !element.data.target.startsWith('observed:'))),
  );
  const connectedIds = new Set(filteredEdges.flatMap((edge) => [edge.data.source, edge.data.target]));
  const filteredNodes = elements.filter(
    (element): element is Extract<TopologyElement, { group: 'nodes' }> =>
      element.group === 'nodes'
      && (element.data.kind === 'registered' || (!registeredOnly && connectedIds.has(element.data.id))),
  );
  const filteredElements: TopologyElement[] = [...filteredNodes, ...filteredEdges];
  const nodeCount = filteredElements.filter((element) => element.group === 'nodes').length;
  const linkCount = filteredElements.filter((element) => element.group === 'edges').length;
  const saveManualLinks = (links: typeof manualLinks) => {
    setManualLinks(links);
    localStorage.setItem(TOPOLOGY_MANUAL_LINKS_KEY, JSON.stringify(links));
  };
  const selectedDevice = devices.data.find((device) => device.id === selectedDeviceId) ?? null;
  // Editing or deleting isn't built for this page — hand off to Inventory,
  // which already owns the device mutation and safety-gate wiring, rather
  // than duplicating it here for a second entry point.
  const focusInInventory = (device: { id: string }) => onFocusDevice?.(device.id);

  return (
    <div
      className={
        selectedDevice === null
          ? 'workspace-layout workspace-layout--inspector-collapsed'
          : 'workspace-layout'
      }
    >
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
                <span><i className="topology-line topology-line--cdp" /> CDP</span>
                <span><i className="topology-line topology-line--lldp" /> LLDP</span>
                <span><i className="topology-line topology-line--manual" /> Unverified link</span>
              </div>
              <div className="topology-filters">
                <label className="usb-console-echo">
                  <input type="checkbox" checked={showCdp} onChange={(event) => setShowCdp(event.target.checked)} />
                  CDP
                </label>
                <label className="usb-console-echo">
                  <input type="checkbox" checked={showLldp} onChange={(event) => setShowLldp(event.target.checked)} />
                  LLDP
                </label>
                <label className="usb-console-echo">
                  <input
                    type="checkbox"
                    checked={registeredOnly}
                    onChange={(event) => setRegisteredOnly(event.target.checked)}
                  />
                  Registered only
                </label>
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
          <TopologyCanvas
            elements={filteredElements}
            onNodeTap={setSelectedDeviceId}
            selectedDeviceId={selectedDeviceId}
          />
          <p className="topology-note">
            Drag nodes to save positions in this browser. Observed nodes remain evidence, not inventory records.
            Manual links stay local and are always labeled UNVERIFIED.
          </p>
        </section>
      </main>
      {selectedDevice === null ? null : (
        <DeviceInspector
          key={selectedDevice.id}
          device={selectedDevice}
          onClose={() => setSelectedDeviceId(undefined)}
          onEdit={focusInInventory}
          onDelete={focusInInventory}
        />
      )}
    </div>
  );
}

export default TopologyPage;
