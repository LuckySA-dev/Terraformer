import { classifyDeviceRole } from '../src/features/topology/topology';
import { deviceIcon } from '../src/features/topology/deviceIcons';

it('reads a Catalyst as a switch even though its banner also says router', () => {
  // Catalyst L3 platforms advertise routing in their platform string; the
  // icon should still be a switch.
  expect(classifyDeviceRole('cisco WS-C3750X-48P', 'Layer 3 Router/Switch')).toBe('switch');
});

it('recognises common Cisco router families', () => {
  expect(classifyDeviceRole('ISR4331/K9')).toBe('router');
  expect(classifyDeviceRole('cisco ASR1001-X')).toBe('router');
  expect(classifyDeviceRole('CSR1000V')).toBe('router');
});

it('recognises firewalls ahead of everything else', () => {
  expect(classifyDeviceRole('FortiGate-60F')).toBe('firewall');
  expect(classifyDeviceRole('Cisco ASA5516')).toBe('firewall');
});

it('falls back to an endpoint when nothing identifies the device', () => {
  expect(classifyDeviceRole(null, undefined, '')).toBe('endpoint');
  expect(classifyDeviceRole('some-unknown-box')).toBe('endpoint');
});

it('reads the operator naming convention when no model was reported', () => {
  // A device that has not returned facts yet has only its name and a driver
  // key, and cisco_iosxe runs on both routers and switches. Falling through to
  // 'endpoint' drew Cisco switches as desktop computers on the canvas.
  expect(classifyDeviceRole(null, null, 'cisco_iosxe', 'SW1')).toBe('switch');
  expect(classifyDeviceRole(null, null, 'cisco_iosxe', 'core-sw-01')).toBe('switch');
  expect(classifyDeviceRole(null, null, 'cisco_iosxe', 'R1')).toBe('router');
  expect(classifyDeviceRole(null, null, 'cisco_iosxe', 'RTR-2')).toBe('router');
  expect(classifyDeviceRole(null, null, 'fortinet_fortios', 'FW1')).toBe('firewall');
});

it('lets a reported model outrank the operator name', () => {
  // Precedence is the order of ROLE_PATTERNS, not the argument order: the
  // name-convention patterns are tested last on purpose.
  expect(classifyDeviceRole('ISR4331/K9', null, 'cisco_iosxe', 'SW1')).toBe('router');
  expect(classifyDeviceRole('cisco WS-C2960X', null, 'cisco_iosxe', 'R1')).toBe('switch');
});

it('does not read an interface name as a device role', () => {
  // These strings travel with a device but never identify one.
  expect(classifyDeviceRole('GigabitEthernet1/0/1')).toBe('endpoint');
  expect(classifyDeviceRole('unknown-hardware')).toBe('endpoint');
});

it('ignores blank hints instead of tripping over them', () => {
  expect(classifyDeviceRole(undefined, 'ISR4331')).toBe('router');
});

it('produces a self-contained svg data uri per role', () => {
  // Cytoscape paints to canvas, so the icon has to be an inline image with no
  // external reference and no CSS variable to resolve.
  for (const role of ['router', 'switch', 'firewall', 'endpoint'] as const) {
    const uri = deviceIcon(role, '#3fbfa5', '#0d1416');
    expect(uri.startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true);
    const decoded = decodeURIComponent(uri.split(',')[1] ?? '');
    expect(decoded).toContain('<svg');
    expect(decoded).toContain('#3fbfa5');
    expect(decoded).not.toContain('var(--');
    // The xmlns is a namespace identifier, not a fetch. What must not appear
    // is an actual external reference the canvas would try to load.
    expect(decoded).not.toContain('href');
    expect(decoded).not.toContain('url(');
  }
});

it('tints the same role differently so status is readable from the icon', () => {
  expect(deviceIcon('router', '#3fbfa5', '#000')).not.toBe(deviceIcon('router', '#f08a8f', '#000'));
});
