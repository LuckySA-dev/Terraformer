import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

describe('serial permissions policy', () => {
  it('allows same-origin serial on the production document response', () => {
    const nginx = read('../nginx.conf');
    expect(nginx).toContain('serial=(self)');
    expect(nginx.match(/serial=\(self\)/g)).toHaveLength(2);
  });

  it('sets the same policy on the Vite development server', () => {
    expect(read('../vite.config.ts')).toContain(
      "'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), serial=(self)'",
    );
  });
});
