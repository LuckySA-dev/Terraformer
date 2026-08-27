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

/** What to draw a node as. Mirrors how EVE-NG/GNS3 label a lab topology. */
export type DeviceRole = 'router' | 'switch' | 'firewall' | 'endpoint';

// Matched against model/platform strings, most specific first. A switch that
// also says "Router" in its platform banner (Catalyst L3 does) must still
// come out a switch, so the switch families are tested before the generic
// router words.
// No trailing \b on the model-prefix families: a real platform string is
// "ISR4331/K9" or "ASA5516", where the family runs straight into a digit and
// a word boundary never occurs.
const ROLE_PATTERNS: readonly (readonly [RegExp, DeviceRole])[] = [
  [/\b(?:asa|firepower|fortigate|fortiwifi|palo\s?alto|pan-?os|srx)/i, 'firewall'],
  [/\bfirewall\b/i, 'firewall'],
  [/\b(?:catalyst|nexus|ws-c|c9[2-6]\d{2}|c3[57]\d{2}|me-\d|sg\d{3})/i, 'switch'],
  [/\bswitch\b/i, 'switch'],
  [/\b(?:isr|asr|csr|ncs|iosv|vios)/i, 'router'],
  [/\brouter\b/i, 'router'],
];

/**
 * Best-effort role from whatever identifying text a device reported.
 *
 * Deliberately a guess, and only ever drives the icon: nothing about safety,
 * reachability or capability keys off it, so a wrong guess costs a wrong
 * picture and nothing else.
 */
export function classifyDeviceRole(...hints: (string | null | undefined)[]): DeviceRole {
  const haystack = hints.filter((hint): hint is string => Boolean(hint)).join(' ');
  for (const [pattern, role] of ROLE_PATTERNS) {
    if (pattern.test(haystack)) return role;
  }
  return 'endpoint';
}

export type TopologyElement =
  | {
      group: 'nodes';
      data: {
        id: string;
        label: string;
        kind: 'registered' | 'observed';
        role: DeviceRole;
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
        /** Port at each end, drawn beside the node it belongs to. */
        sourcePort: string;
        targetPort: string;
        protocol: DeviceNeighbor['protocol'] | 'manual';
        /** Both ends are registered devices, not a one-sided sighting. */
        verified: boolean;
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
        role: classifyDeviceRole(device.facts.model, device.facts.vendor, device.vendor),
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
            // A neighbour is only ever known by what it advertised, so its
            // platform banner is the only hint available.
            role: classifyDeviceRole(neighbor.platform),
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
          sourcePort: abbreviateInterface(neighbor.local_interface),
          targetPort: abbreviateInterface(neighbor.remote_interface),
          protocol: neighbor.protocol,
          verified: registeredTarget !== undefined,
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
        sourcePort: '',
        targetPort: '',
        protocol: 'manual',
        // Operator-drawn: asserted, never observed, so never "verified".
        verified: false,
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
