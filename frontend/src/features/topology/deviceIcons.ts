import type { DeviceRole } from './topology';

/**
 * Node glyphs for the topology canvas, in the shape vocabulary EVE-NG and
 * GNS3 use -- a router is a puck with opposed arrows, a switch is a slab with
 * parallel arrows, a firewall is a brick wall.
 *
 * These are data-URI SVGs rather than the app's lucide icons because
 * cytoscape paints to its own canvas: it takes an image URL, not a React
 * element, and cannot resolve a CSS custom property. That also means the
 * colour has to be baked in per theme, which is why every builder takes it
 * as an argument.
 */

const svg = (body: string): string =>
  // encodeURIComponent, not base64: it survives the '#' in colour literals,
  // which would otherwise terminate the data URI.
  `data:image/svg+xml;charset=utf-8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">${body}</svg>`,
  )}`;

function router(color: string, ink: string): string {
  return svg(
    `<ellipse cx="32" cy="32" rx="28" ry="19" fill="${color}"/>` +
      `<g stroke="${ink}" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round" fill="none">` +
      `<path d="M20 26h16"/><path d="M31 21l5 5-5 5"/>` +
      `<path d="M44 38H28"/><path d="M33 43l-5-5 5-5"/>` +
      `</g>`,
  );
}

function switchIcon(color: string, ink: string): string {
  return svg(
    `<path d="M6 40 L20 22 H58 L44 40 Z" fill="${color}"/>` +
      `<path d="M6 40 L20 22 H58 L44 40 Z" fill="none" stroke="${ink}" stroke-width="2.4" ` +
      `stroke-linejoin="round" opacity="0.35"/>` +
      `<g stroke="${ink}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" fill="none">` +
      `<path d="M22 34h16"/><path d="M33 29l5 5-5 5"/>` +
      `<path d="M42 28H26"/><path d="M31 23l-5 5 5 5"/>` +
      `</g>`,
  );
}

function firewall(color: string, ink: string): string {
  return svg(
    `<rect x="7" y="15" width="50" height="34" rx="3" fill="${color}"/>` +
      `<g stroke="${ink}" stroke-width="2.6" stroke-linecap="round" opacity="0.75">` +
      `<path d="M7 26h50"/><path d="M7 38h50"/>` +
      `<path d="M24 15v11"/><path d="M40 15v11"/>` +
      `<path d="M16 26v12"/><path d="M32 26v12"/><path d="M48 26v12"/>` +
      `<path d="M24 38v11"/><path d="M40 38v11"/>` +
      `</g>`,
  );
}

function endpoint(color: string, ink: string): string {
  return svg(
    `<rect x="9" y="14" width="46" height="30" rx="3" fill="${color}"/>` +
      `<rect x="15" y="20" width="34" height="18" rx="1.5" fill="${ink}" opacity="0.28"/>` +
      `<path d="M22 50h20" stroke="${ink}" stroke-width="3.4" stroke-linecap="round"/>` +
      `<path d="M32 44v6" stroke="${ink}" stroke-width="3.4" stroke-linecap="round"/>`,
  );
}

const BUILDERS: Record<DeviceRole, (color: string, ink: string) => string> = {
  router,
  switch: switchIcon,
  firewall,
  endpoint,
};

export function deviceIcon(role: DeviceRole, color: string, ink: string): string {
  return BUILDERS[role](color, ink);
}

export const DEVICE_ROLES: readonly DeviceRole[] = ['router', 'switch', 'firewall', 'endpoint'];
