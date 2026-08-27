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
  { id: 'global', label: 'Global' },
  { id: 'switching', label: 'Switching' },
  { id: 'interface', label: 'Interface' },
  { id: 'routing', label: 'Routing' },
];

/** An entry the backend can execute today. */
interface AvailableEntry {
  id: string;
  section: ConfigSectionId;
  label: string;
  available: true;
  changeType: ChangeType;
  /** The change targets a named interface rather than a global or VLAN id. */
  targetsInterface: boolean;
}

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

const planned = (detail: string) =>
  `Not implemented yet. ${detail} There is no API, worker job or driver path for it, so this ` +
  'entry cannot send anything to the device.';

export const CONFIG_ENTRIES: readonly ConfigEntry[] = [
  {
    id: 'hostname',
    section: 'global',
    label: 'Hostname',
    available: false,
    reason: planned('It needs a global (non-interface) change type in the apply pipeline.'),
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
    id: 'interface-description',
    section: 'interface',
    label: 'Description',
    available: true,
    changeType: 'interface_description',
    targetsInterface: true,
  },
  {
    id: 'interface-admin-state',
    section: 'interface',
    label: 'Port status',
    available: true,
    changeType: 'interface_admin_state',
    targetsInterface: true,
  },
  {
    id: 'interface-access-vlan',
    section: 'interface',
    label: 'Access VLAN',
    available: true,
    changeType: 'interface_access_vlan',
    targetsInterface: true,
  },
  {
    id: 'interface-ip',
    section: 'interface',
    label: 'IP address / SVI',
    available: false,
    reason: planned(
      'Changing the address a device is managed on can cut the session that is applying it, ' +
      'so it needs its own guard before it is offered.',
    ),
  },
  {
    id: 'interface-trunk',
    section: 'interface',
    label: 'Trunk / allowed VLANs',
    available: false,
    reason: planned('It needs validation against the VLANs the switch actually has.'),
  },
  {
    id: 'routing-static',
    section: 'routing',
    label: 'Static route',
    available: false,
    reason: planned('It needs a post-check that reads the routing table back.'),
  },
  {
    id: 'routing-rip',
    section: 'routing',
    label: 'RIP v1 / v2',
    available: false,
    reason: planned('Dynamic routing changes converge over time, so a single post-check does not settle them.'),
  },
  {
    id: 'routing-eigrp',
    section: 'routing',
    label: 'EIGRP',
    available: false,
    reason: planned('Dynamic routing changes converge over time, so a single post-check does not settle them.'),
  },
  {
    id: 'routing-ospf',
    section: 'routing',
    label: 'OSPF',
    available: false,
    reason: planned('Dynamic routing changes converge over time, so a single post-check does not settle them.'),
  },
  {
    id: 'routing-bgp',
    section: 'routing',
    label: 'BGP',
    available: false,
    reason: planned('Dynamic routing changes converge over time, so a single post-check does not settle them.'),
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
