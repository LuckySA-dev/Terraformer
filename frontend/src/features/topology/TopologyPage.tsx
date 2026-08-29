import { useQueries, useQuery } from '@tanstack/react-query';
import cytoscape from 'cytoscape';
import type { LayoutOptions, PresetLayoutOptions, StylesheetJson } from 'cytoscape';
import fcose from 'cytoscape-fcose';
import type { FcoseLayoutOptions } from 'cytoscape-fcose';
import { Bot, Network, RefreshCw, Trash2 } from 'lucide-react';
import { lazy, Suspense, useEffect, useRef, useState } from 'react';
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
import { DEVICE_ROLES, deviceIcon } from './deviceIcons';

const AssistantSidebar = lazy(() =>
  import('../assistant/AssistantSidebar').then((module) => ({
    default: module.AssistantSidebar,
  })),
);

/**
 * How many device config windows may be open at once.
 *
 * Chosen so the cascade stays on screen and the stacking order (60 + index)
 * stays below the 70 the menus use and the 100 the modals use. Generous enough
 * that reaching it is a deliberate act rather than an accident.
 */
const MAX_CONFIG_WINDOWS = 6;

const DeviceConfigWindow = lazy(() =>
  import('../config/DeviceConfigWindow').then((module) => ({
    default: module.DeviceConfigWindow,
  })),
);

cytoscape.use(fcose);

/**
 * Ceiling for the zoom `fit` is allowed to settle on. 1 renders a node at its
 * declared 52x40, which is the size the glyphs were drawn for; a sparse graph
 * is centred with space around it instead of magnified to fill the canvas.
 */
const RESTING_ZOOM_CAP = 1;

// Cytoscape renders to its own canvas, not the DOM, so its style values are
// literal colors resolved once at graph-build time -- a CSS var() string
// here would not be looked up the way it is in a stylesheet. Two fixed
// palettes, chosen by prefers-color-scheme, stand in for the CSS custom
// properties the rest of the app uses.
function buildTopologyStyle(dark: boolean): StylesheetJson {
  const c = dark
    ? {
        text: '#e6ecea',
        textBg: '#151f22',
        registered: '#3fbfa5',
        unreachable: '#f08a8f',
        observedFill: '#5c6b70',
        observedBorder: '#9aa8ad',
        iconInk: '#0d1416',
        edge: '#5b706b',
        edgeText: '#9aa8ad',
        edgeTextBg: '#111a1c',
        lldp: '#8891c9',
        manual: '#d99a3f',
      }
    : {
        text: '#24312f',
        textBg: '#ffffff',
        registered: '#1c8a74',
        unreachable: '#ba4650',
        observedFill: '#9fb0ab',
        observedBorder: '#5f716c',
        iconInk: '#ffffff',
        edge: '#7e968f',
        edgeText: '#556762',
        edgeTextBg: '#f7faf9',
        lldp: '#7180b9',
        manual: '#b17b24',
      };
  // One image per role x tint. Built once per theme rather than per node so a
  // 200-node graph does not re-encode the same SVG 200 times.
  const iconFor = (tint: string) =>
    Object.fromEntries(
      DEVICE_ROLES.map((role) => [role, deviceIcon(role, tint, c.iconInk)]),
    ) as Record<(typeof DEVICE_ROLES)[number], string>;
  const registeredIcons = iconFor(c.registered);
  const unreachableIcons = iconFor(c.unreachable);
  const observedIcons = iconFor(c.observedFill);

  const roleRules = (
    icons: Record<(typeof DEVICE_ROLES)[number], string>,
    qualifier: string,
  ): StylesheetJson =>
    DEVICE_ROLES.map((role) => ({
      selector: `node[role = "${role}"]${qualifier}`,
      style: { 'background-image': icons[role] },
    }));

  return [
    {
      selector: 'node',
      style: {
        label: 'data(label)',
        // The glyph is the node; the box behind it stays out of the way so
        // the silhouette reads the way it does in EVE-NG or GNS3.
        'background-color': 'transparent',
        'background-opacity': 0,
        'background-fit': 'contain',
        'background-clip': 'none',
        'background-image-containment': 'over',
        'border-width': 0,
        shape: 'rectangle',
        color: c.text,
        'font-size': 10,
        'font-weight': 700,
        'text-background-color': c.textBg,
        'text-background-opacity': 0.92,
        'text-background-padding': '3px',
        'text-background-shape': 'roundrectangle',
        'text-margin-y': 6,
        'text-valign': 'bottom',
        'text-wrap': 'wrap',
        'text-max-width': '92px',
        height: 40,
        width: 52,
      },
    },
    ...roleRules(registeredIcons, '[kind = "registered"]'),
    ...roleRules(observedIcons, '[kind = "observed"]'),
    // Ordered after the kind rules so an unreachable registered device wins.
    ...roleRules(unreachableIcons, '[status = "unreachable"]'),
    {
      selector: 'node[kind = "observed"]',
      style: {
        // Evidence, not inventory: dimmer and italic-feeling, so it never
        // reads as a device the operator actually registered.
        opacity: 0.85,
        color: c.observedBorder,
      },
    },
    {
      selector: 'node.is-selected',
      style: {
        'border-width': 3,
        'border-color': c.manual,
        'border-opacity': 1,
        shape: 'roundrectangle',
        'background-color': c.manual,
        'background-opacity': 0.14,
        'font-size': 12,
        'z-index': 20,
      },
    },
    {
      selector: 'edge',
      style: {
        width: 2.5,
        'line-color': c.edge,
        // A cable between two boxes, not an arrow: CDP/LLDP adjacency is
        // mutual, and the arrowhead implied a direction that does not exist.
        'target-arrow-shape': 'none',
        'source-arrow-shape': 'none',
        'curve-style': 'bezier',
        // Port names sit at the end of the cable they belong to -- which is
        // how a patch schedule reads, and it stops two ports being mistaken
        // for one label floating mid-span.
        'source-label': 'data(sourcePort)',
        'target-label': 'data(targetPort)',
        'source-text-offset': 26,
        'target-text-offset': 26,
        color: c.edgeText,
        'font-size': 7,
        'font-weight': 600,
        'text-background-color': c.edgeTextBg,
        'text-background-opacity': 0.95,
        'text-background-padding': '2px',
        'text-background-shape': 'roundrectangle',
        'text-rotation': 'autorotate',
        // Drop port labels once they would render too small to read, so a
        // zoomed-out view shows topology shape instead of a wall of text.
        'min-zoomed-font-size': 7,
      },
    },
    {
      selector: 'edge[protocol = "lldp"]',
      style: { 'line-color': c.lldp, 'line-style': 'dashed', 'line-dash-pattern': [7, 3] },
    },
    {
      selector: 'edge[protocol = "manual"]',
      style: {
        'line-color': c.manual,
        'line-style': 'dotted',
        width: 2,
        label: 'data(label)',
        'text-rotation': 'autorotate',
      },
    },
    {
      // Both ends registered means the link is corroborated from inventory on
      // each side, so it earns a heavier line than a one-sided sighting.
      // Expressed as a data selector rather than a class applied after build:
      // it then survives a rebuild with no extra imperative pass.
      selector: 'edge[?verified]',
      style: { width: 3.5 },
    },
    {
      selector: 'edge.is-incident',
      style: {
        'line-color': c.manual,
        'z-index': 15,
        width: 4,
        'font-size': 9,
      },
    },
  ];
}

// Identity of the graph's *content*, ignoring array identity and saved
// positions. The build effect keys off this so unrelated re-renders — a node
// tap, a refresh poll, a filter toggle that changes nothing — never destroy
// and re-lay-out the graph under the operator.
function graphSignature(elements: TopologyElement[]): string {
  return elements
    .map((element) =>
      element.group === 'nodes'
        ? `n:${element.data.id}:${element.data.label}:${element.data.kind}:${element.data.role}:${element.data.status}`
        : `e:${element.data.id}:${element.data.source}:${element.data.target}:${element.data.label}:${String(element.data.verified)}`,
    )
    .join('|');
}

function TopologyCanvas({
  elements,
  onNodeTap,
  onNodeConfigure,
  selectedDeviceId,
}: {
  elements: TopologyElement[];
  onNodeTap?: (deviceId: string) => void;
  onNodeConfigure?: (deviceId: string) => void;
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
  const onNodeConfigureRef = useRef(onNodeConfigure);
  useEffect(() => {
    onNodeConfigureRef.current = onNodeConfigure;
  }, [onNodeConfigure]);
  const elementsRef = useRef(elements);
  useEffect(() => {
    elementsRef.current = elements;
  }, [elements]);
  const signature = graphSignature(elements);

  const [prefersDark, setPrefersDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches,
  );
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (event: MediaQueryListEvent) => setPrefersDark(event.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

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
          // Roomier than the defaults: the icons are wider than the old dots
          // and each cable now carries a port label at both ends, so a tight
          // layout put text on top of text.
          nodeSeparation: 140,
          idealEdgeLength: 170,
          // Keeps access-layer nodes from being flung far from their uplink,
          // which is what made the old graph read as a ring rather than a
          // hierarchy.
          gravity: 0.4,
          gravityRange: 3.2,
          nestingFactor: 0.2,
          numIter: 3500,
        };
    const graph = cytoscape({
      container: container.current,
      elements,
      style: buildTopologyStyle(prefersDark),
      // cytoscape-fcose's own option type doesn't line up byte-for-byte with
      // cytoscape core's LayoutOptions union under exactOptionalPropertyTypes,
      // even though the shape fcose actually expects at runtime is correct.
      layout: layout as LayoutOptions,
      boxSelectionEnabled: false,
      minZoom: 0.35,
      maxZoom: 2.5,
    });
    // `fit` scales the graph until it fills the canvas, which is what an
    // operator wants for a busy network and exactly wrong for a small one: two
    // nodes were being blown up to the 2.5x ceiling, so the glyphs rendered
    // several times their intended size and read as clip art rather than a
    // diagram. Cap the resting zoom and re-centre; panning and manual zoom are
    // untouched, so the operator can still zoom in past this themselves.
    const capInitialZoom = () => {
      if (graph.zoom() > RESTING_ZOOM_CAP) {
        graph.zoom(RESTING_ZOOM_CAP);
        graph.center();
      }
    };
    // Called both now and on layoutstop: a non-animated layout has usually
    // already settled by the time the constructor returns, but `preset` and
    // `fcose` do not guarantee it. Capping is idempotent, so running twice is
    // free and running once is enough.
    capInitialZoom();
    graph.one('layoutstop', capInitialZoom);
    graph.on('dragfree', 'node', () => {
      // graph.nodes() is only whatever the active protocol/registered-only
      // filter currently shows -- writing that alone would silently drop the
      // saved position of every node the filter is hiding right now. Merge
      // onto the full stored set instead of replacing it.
      const current = Object.fromEntries(
        graph.nodes().map((node) => [node.id(), node.position()]),
      );
      localStorage.setItem(
        TOPOLOGY_POSITIONS_KEY,
        JSON.stringify({ ...loadTopologyPositions(localStorage), ...current }),
      );
    });
    graph.on('tap', 'node', (event: cytoscape.EventObjectNode) => {
      const id = event.target.id();
      if (id.startsWith('device:')) onNodeTapRef.current?.(id.slice('device:'.length));
    });
    // Double-click opens the config window, the way Packet Tracer opens a
    // device. Only registered devices have one: an observed node is a sighting
    // from a neighbour table, not something this application can configure.
    graph.on('dbltap', 'node', (event: cytoscape.EventObjectNode) => {
      const id = event.target.id();
      if (id.startsWith('device:')) onNodeConfigureRef.current?.(id.slice('device:'.length));
    });
    graphRef.current = graph;
    return () => {
      graphRef.current = null;
      graph.destroy();
    };
    // Rebuilds on a theme change too: colors are baked into the stylesheet
    // at build time here, not read live, so a build keyed on signature alone
    // would leave the graph on the old palette after the OS theme switches.
  }, [signature, prefersDark]);

  // Selection is a style change, not a rebuild — highlighting the tapped node
  // must never disturb the layout the operator is looking at.
  useEffect(() => {
    const graph = graphRef.current;
    if (graph === null) return;
    graph.elements('.is-incident').removeClass('is-incident');
    graph.nodes('.is-selected').removeClass('is-selected');
    if (selectedDeviceId !== undefined) {
      const node = graph.getElementById(`device:${selectedDeviceId}`);
      node.addClass('is-selected');
      // Light up that device's cables too: on a dense graph, finding which
      // links belong to the node you just tapped is the actual question.
      node.connectedEdges().addClass('is-incident');
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
  /**
   * Every device with a config window open, oldest first. Packet Tracer lets
   * several devices be configured at once, so this is a list rather than one
   * id -- and its order is the stacking order, so the window last pressed is
   * the one on top.
   */
  const [configuringDeviceIds, setConfiguringDeviceIds] = useState<string[]>([]);
  const [assistantOpen, setAssistantOpen] = useState(false);

  // One right rail, shared: the inspector and the assistant are mutually
  // exclusive, so each opener closes the other.
  const openAssistant = () => {
    setAssistantOpen(true);
    setSelectedDeviceId(undefined);
  };
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
  // Windows for devices that have since been deleted drop out on their own.
  const configuringDevices = configuringDeviceIds.flatMap(
    (id) => devices.data.find((device) => device.id === id) ?? [],
  );
  /** Opens a window, or raises the one already open for that device. */
  const openConfigWindow = (deviceId: string) => {
    setConfiguringDeviceIds((current) =>
      // Least recently focused goes when the cap is reached. Unbounded, a
      // handful of double-clicks put windows off the side of the screen, gave
      // each one its own poller and a terminal, and walked the stacking order
      // (60 + index) up into the layer the menus and dialogs use.
      [...current.filter((id) => id !== deviceId), deviceId].slice(-MAX_CONFIG_WINDOWS),
    );
  };
  const raiseConfigWindow = (deviceId: string) => {
    setConfiguringDeviceIds((current) =>
      current.at(-1) === deviceId
        ? current
        : [...current.filter((id) => id !== deviceId), deviceId],
    );
  };
  // Editing or deleting isn't built for this page — hand off to Inventory,
  // which already owns the device mutation and safety-gate wiring, rather
  // than duplicating it here for a second entry point.
  const focusInInventory = (device: { id: string }) => onFocusDevice?.(device.id);

  return (
    <div
      className={
        selectedDevice === null && !assistantOpen
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
                <span className="topology-legend__note">Thicker line = seen from both ends</span>
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
            onNodeTap={(id) => {
              setAssistantOpen(false);
              setSelectedDeviceId(id);
            }}
            onNodeConfigure={openConfigWindow}
            selectedDeviceId={selectedDeviceId}
          />
          <p className="topology-note">
            Click a device to inspect it, or double-click to open its configuration window. Drag
            nodes to save positions in this browser. Observed nodes remain evidence, not inventory
            records. Manual links stay local and are always labeled UNVERIFIED.
          </p>
        </section>
        <section className="topology-panel topology-assistant">
          <div className="topology-toolbar">
            <div>
              <h2>Ask about the whole network</h2>
              <span>Opens in the right sidebar -- pick the devices it should be about</span>
            </div>
            <Button size="small" onClick={openAssistant}>
              <Bot size={13} /> Open assistant
            </Button>
          </div>
        </section>
      </main>
      {!assistantOpen ? null : (
        <Suspense fallback={null}>
          <AssistantSidebar
            onClose={() => setAssistantOpen(false)}
            onOpenInventory={() => onFocusDevice?.(selectedDeviceId ?? '')}
          />
        </Suspense>
      )}
      {selectedDevice === null ? null : (
        <DeviceInspector
          key={selectedDevice.id}
          device={selectedDevice}
          onClose={() => setSelectedDeviceId(undefined)}
          onEdit={focusInInventory}
          onDelete={focusInInventory}
        />
      )}
      {configuringDevices.map((device, index) => (
        <Suspense key={device.id} fallback={null}>
          <DeviceConfigWindow
            device={device}
            // Cascaded so a second window does not land exactly on the first.
            initialPosition={{ x: 132 + index * 28, y: 78 + index * 28 }}
            zIndex={60 + index}
            onFocus={() => raiseConfigWindow(device.id)}
            onClose={() =>
              setConfiguringDeviceIds((current) => current.filter((id) => id !== device.id))
            }
          />
        </Suspense>
      ))}
    </div>
  );
}

export default TopologyPage;
