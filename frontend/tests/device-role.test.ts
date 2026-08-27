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
