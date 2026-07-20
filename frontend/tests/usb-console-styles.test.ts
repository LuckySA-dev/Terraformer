import { readFileSync } from 'node:fs';

const styles = readFileSync('src/styles.css', 'utf8');

describe('Manual USB Console styles', () => {
  it('uses a light pre-connection surface with readable inset text', () => {
    expect(styles).toContain(`.terminal-session:has(.usb-console-settings) {
  border-color: var(--border);
  background: var(--surface);
}`);
    expect(styles).toContain(`.terminal-session:has(.usb-console-settings) .usb-console-authorization {
  color: var(--ink);
}`);
    expect(styles).toContain(`.terminal-session:has(.usb-console-settings) .terminal-note {
  margin: 0;
  padding: 0 9px 9px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.5;
}`);
  });
});
