import type { Device, DeviceNeighbor } from '../../types/api';

// ponytail: browser-local layout; move to /api/topologies when backup/restore enters scope.
export const TOPOLOGY_POSITIONS_KEY = 'terraformer.topology.positions';
export const TOPOLOGY_MANUAL_LINKS_KEY = 'terraformer.topology.manual-links';

export interface NeighborGroup {
  deviceId: string;
  neighbors: DeviceNeighbor[];
}

export interface TopologyPosition {
  x: number;
  y: number;
}

export type TopologyPositions = Record<string, TopologyPosition>;

export interface ManualTopologyLink {
  id: string;
  sourceDeviceId: string;
  targetDeviceId: string;
}

export type TopologyElement =
  | {
      group: 'nodes';
      data: {
        id: string;
        label: string;
        kind: 'registered' | 'observed';
        status: Device['status'] | 'observed';
      };
      position?: TopologyPosition;
    }
  | {
      group: 'edges';
      data: {
        id: string;
        source: string;
        target: string;
        label: string;
        protocol: DeviceNeighbor['protocol'] | 'manual';
      };
    };

// Cisco's own short forms. Full names ("GigabitEthernet1/0/1") make edge
// labels several times longer than the links they sit on, which is what makes
// a dense graph unreadable.
const INTERFACE_ABBREVIATIONS: readonly (readonly [RegExp, string])[] = [
  [/^TwentyFiveGigE/i, 'Twe'],
  [/^TenGigabitEthernet/i, 'Te'],
  [/^FortyGigabitEthernet/i, 'Fo'],
  [/^HundredGigE/i, 'Hu'],
  [/^GigabitEthernet/i, 'Gi'],
  [/^FastEthernet/i, 'Fa'],
  [/^Ethernet/i, 'Et'],
  [/^Port-channel/i, 'Po'],
  [/^Vlan/i, 'Vl'],
  [/^Loopback/i, 'Lo'],
];

export function abbreviateInterface(name: string): string {
  for (const [pattern, short] of INTERFACE_ABBREVIATIONS) {
    if (pattern.test(name)) return name.replace(pattern, short);
  }
  return name;
}

/** Observed neighbours report FQDNs; the hostname alone is what identifies them on a graph. */
export function shortenDeviceLabel(name: string): string {
  const [hostname] = name.split('.');
  return hostname !== undefined && hostname.length > 0 ? hostname : name;
}

export function buildTopologyElements(
  devices: Device[],
  neighborGroups: NeighborGroup[],
  positions: TopologyPositions = {},
  manualLinks: ManualTopologyLink[] = [],
): TopologyElement[] {
  const registeredByAddress = new Map(
    devices.map((device) => [device.management_address, device]),
  );
  const elements: TopologyElement[] = devices.map((device) => {
    const id = `device:${device.id}`;
    return {
      group: 'nodes',
      data: {
        id,
        label: device.facts.hostname ?? device.name,
        kind: 'registered',
        status: device.status,
      },
      ...(positions[id] === undefined ? {} : { position: positions[id] }),
    };
  });

  for (const { deviceId, neighbors } of neighborGroups) {
    for (const neighbor of neighbors) {
      const registeredTarget =
        neighbor.management_address === null
          ? undefined
          : registeredByAddress.get(neighbor.management_address);
      const targetId =
        registeredTarget === undefined
          ? `observed:${neighbor.id}`
          : `device:${registeredTarget.id}`;

      if (registeredTarget === undefined) {
        elements.push({
          group: 'nodes',
          data: {
            id: targetId,
            label: shortenDeviceLabel(neighbor.remote_device_name),
            kind: 'observed',
            status: 'observed',
          },
          ...(positions[targetId] === undefined ? {} : { position: positions[targetId] }),
        });
      }
      elements.push({
        group: 'edges',
        data: {
          id: `neighbor:${neighbor.id}`,
          source: `device:${deviceId}`,
          target: targetId,
          label: `${abbreviateInterface(neighbor.local_interface)} → ${abbreviateInterface(neighbor.remote_interface)}`,
          protocol: neighbor.protocol,
        },
      });
    }
  }
  const registeredIds = new Set(devices.map((device) => device.id));
  for (const link of manualLinks) {
    if (
      link.sourceDeviceId === link.targetDeviceId ||
      !registeredIds.has(link.sourceDeviceId) ||
      !registeredIds.has(link.targetDeviceId)
    ) continue;
    elements.push({
      group: 'edges',
      data: {
        id: `manual:${link.id}`,
        source: `device:${link.sourceDeviceId}`,
        target: `device:${link.targetDeviceId}`,
        label: 'UNVERIFIED',
        protocol: 'manual',
      },
    });
  }
  return elements;
}

export function loadTopologyPositions(storage: Pick<Storage, 'getItem'>): TopologyPositions {
  try {
    const parsed: unknown = JSON.parse(storage.getItem(TOPOLOGY_POSITIONS_KEY) ?? '{}');
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed).filter(
        (entry): entry is [string, TopologyPosition] => {
          const value: unknown = entry[1];
          return (
            typeof value === 'object' &&
            value !== null &&
            'x' in value &&
            'y' in value &&
            typeof value.x === 'number' &&
            Number.isFinite(value.x) &&
            typeof value.y === 'number' &&
            Number.isFinite(value.y)
          );
        },
      ),
    );
  } catch {
    return {};
  }
}

export function loadManualTopologyLinks(
  storage: Pick<Storage, 'getItem'>,
): ManualTopologyLink[] {
  try {
    const parsed: unknown = JSON.parse(storage.getItem(TOPOLOGY_MANUAL_LINKS_KEY) ?? '[]');
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((entry): entry is ManualTopologyLink => {
      const value: unknown = entry;
      return (
        typeof value === 'object' &&
        value !== null &&
        'id' in value &&
        typeof value.id === 'string' &&
        'sourceDeviceId' in value &&
        typeof value.sourceDeviceId === 'string' &&
        'targetDeviceId' in value &&
        typeof value.targetDeviceId === 'string'
      );
    });
  } catch {
    return [];
  }
}
