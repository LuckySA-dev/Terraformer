import type { ChangeType } from '../../types/api';

/**
 * The catalog behind the Packet Tracer-style config window.
 *
 * Packet Tracer can offer every knob because it drives a simulation. This
 * window drives real hardware, so it is split in two: entries that map to a
 * `ChangeType` the backend actually renders, validates, applies and can
 * reverse, and entries that are declared here only so the operator can see
 * where a capability will land. An unavailable entry carries no form and no
 * request path -- it is a label, and `docs/safety-model.md` requires that it
 * stay one until its capability exists end to end.
 */

export type ConfigSectionId = 'global' | 'switching' | 'interface' | 'routing';

export interface ConfigSection {
  id: ConfigSectionId;
  label: string;
}

export const CONFIG_SECTIONS: readonly ConfigSection[] = [
  { id: 'global', label: 'Initial setup' },
  { id: 'switching', label: 'Switching' },
  { id: 'interface', label: 'Interface / IP' },
  { id: 'routing', label: 'Routing' },
];

/** A single change type rendered by the generic target/value form. */
interface SimpleEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: true;
  kind?: undefined;
  changeType: ChangeType;
  /** The change targets a named interface rather than a global or VLAN id. */
  targetsInterface: boolean;
}

/** An entry with a purpose-built screen instead of the generic form. */
interface CustomEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: true;
  kind: 'interface-editor';
}

/** Read-only screen: shows device state rather than staging a change. */
interface InventoryEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: true;
  kind: 'routing-inventory';
}

/** A change that targets the device itself: one value, no target to pick. */
interface GlobalTextEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: true;
  kind: 'global-text';
  changeType: ChangeType;
  valueLabel: string;
  placeholder: string;
  hint: string;
}

/**
 * One network statement in a routing process. The protocol is fixed by which
 * entry the operator picked, so the form asks for the process id and the
 * statement rather than making them assemble "ospf 1" by hand.
 */
export interface RouterNetworkEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: true;
  kind: 'router-network';
  changeType: 'router_network';
  protocol: 'ospf' | 'eigrp' | 'rip';
  /** Placeholder for the network statement, which differs per protocol. */
  placeholder: string;
  hint: string;
}

/**
 * One BGP peer. Separate from the other three protocols because a session is a
 * neighbour and a remote AS rather than a network statement.
 */
export interface BgpNeighborEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: true;
  kind: 'bgp-neighbor';
  changeType: 'bgp_neighbor';
  hint: string;
}

/** An action that runs on its own, with no plan to preview first. */
interface ActionEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: true;
  kind: 'save-config';
}

/** A global change with a fixed set of values rather than free text. */
interface GlobalChoiceEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: true;
  kind: 'global-choice';
  changeType: ChangeType;
  valueLabel: string;
  choices: readonly { value: string; label: string }[];
  hint: string;
}

type AvailableEntry =
  | SimpleEntry
  | CustomEntry
  | InventoryEntry
  | GlobalTextEntry
  | GlobalChoiceEntry
  | RouterNetworkEntry
  | BgpNeighborEntry
  | ActionEntry;

/** A declared-but-unbuilt entry. Rendered disabled, never submittable. */
interface UnavailableEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: false;
  /** Shown to the operator so "greyed out" never reads as "broken". */
  reason: string;
}

export type ConfigEntry = AvailableEntry | UnavailableEntry;


export const CONFIG_ENTRIES: readonly ConfigEntry[] = [
  {
    id: 'hostname',
    section: 'global',
    label: 'Hostname',
    available: true,
    kind: 'global-text',
    changeType: 'hostname',
    valueLabel: 'Hostname',
    placeholder: 'SW2-ACCESS',
    hint: 'Starts with a letter; letters, digits and hyphens only. Rollback restores the name the device reports now.',
  },
  {
    id: 'save-config',
    section: 'global',
    label: 'Save running-config',
    available: true,
    kind: 'save-config',
  },
  {
    id: 'no-domain-lookup',
    section: 'global',
    label: 'Domain lookup',
    available: true,
    kind: 'global-choice',
    changeType: 'domain_lookup',
    valueLabel: 'Name resolution',
    choices: [
      { value: 'off', label: 'off -- a typo at the prompt fails immediately' },
      { value: 'on', label: 'on -- the device resolves hostnames' },
    ],
    hint: 'Off is the usual lab setting: with it on, a mistyped command becomes a DNS lookup that blocks the session until it times out. Rollback restores whichever the device reports now.',
  },
  {
    id: 'vlan-database',
    section: 'switching',
    label: 'VLAN database',
    available: true,
    changeType: 'vlan_name',
    targetsInterface: false,
  },
  {
    // Description, port status and access VLAN were three entries that each
    // opened an empty form, so changing one field meant knowing the current
    // value and retyping it. They are one screen now: pick the port from the
    // table, and every field starts on what the device reported.
    id: 'interfaces',
    section: 'interface',
    label: 'Interfaces',
    available: true,
    kind: 'interface-editor',
  },
  {
    id: 'interface-trunk',
    section: 'interface',
    label: 'Trunk / allowed VLANs',
    available: true,
    changeType: 'interface_trunk_vlans',
    targetsInterface: true,
  },
  {
    // First in the section on purpose: every form under it asks the operator
    // to name a prefix or a process they otherwise had to go find in a
    // terminal first.
    id: 'routing-inventory',
    section: 'routing',
    label: 'Configured routing',
    available: true,
    kind: 'routing-inventory',
  },
  {
    id: 'routing-static',
    section: 'routing',
    label: 'Static route',
    available: true,
    changeType: 'static_route',
    targetsInterface: false,
  },
  {
    id: 'routing-rip',
    section: 'routing',
    label: 'RIP v1 / v2',
    available: true,
    kind: 'router-network',
    changeType: 'router_network',
    protocol: 'rip',
    placeholder: '10.0.0.0',
    hint: 'A classful network. A process this change creates starts at the device default, which is version 1 -- setting the version is not a supported change yet.',
  },
  {
    id: 'routing-eigrp',
    section: 'routing',
    label: 'EIGRP',
    available: true,
    kind: 'router-network',
    changeType: 'router_network',
    protocol: 'eigrp',
    placeholder: '172.16.0.0 0.0.255.255',
    hint: 'A network, with an optional wildcard mask.',
  },
  {
    id: 'routing-ospf',
    section: 'routing',
    label: 'OSPF',
    available: true,
    kind: 'router-network',
    changeType: 'router_network',
    protocol: 'ospf',
    placeholder: '10.0.0.0 0.0.0.255 area 0',
    hint: 'A network, a wildcard mask and an area. A wildcard of 255.255.255.255 enables OSPF on every interface, including the one this device is managed on.',
  },
  {
    id: 'routing-bgp',
    section: 'routing',
    label: 'BGP',
    available: true,
    kind: 'bgp-neighbor',
    changeType: 'bgp_neighbor',
    hint: 'IOS runs one BGP process per device, so this must match the AS already configured if there is one.',
  },
];

export const entriesInSection = (section: ConfigSectionId): ConfigEntry[] =>
  CONFIG_ENTRIES.filter((entry) => entry.section === section);

export const findEntry = (id: string): ConfigEntry | undefined =>
  CONFIG_ENTRIES.find((entry) => entry.id === id);

/**
 * The entry the window opens on. Falls back to the first declared entry only
 * if every capability were ever withdrawn, which keeps this total without a
 * non-null assertion.
 */
export const FIRST_AVAILABLE_ENTRY: ConfigEntry =
  CONFIG_ENTRIES.find((entry) => entry.available) ?? CONFIG_ENTRIES[0] ?? {
    id: 'none',
    section: 'global',
    label: 'Configuration',
    available: false,
    reason: 'No structured change type is available in this build.',
  };
