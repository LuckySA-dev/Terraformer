# Manual USB Console UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Manual USB Console pre-connection card white and readable while preserving the dark connected terminal and all existing behavior.

**Architecture:** Use CSS only. The existing `.usb-console-settings` descendant identifies the pre-connection USB state, so `:has()` can scope the light card without adding React state or changing the shared SSH terminal. A focused source-level CSS regression test provides a deterministic red/green check because jsdom does not perform browser layout.

**Tech Stack:** CSS, Vitest, TypeScript, React 19.

## Global Constraints

- Do not change React components, serial transports, SSH, credentials, discovery, APIs, or backend code.
- The pre-connection USB card is light; the connected xterm surface remains dark.
- Automated verification must not access serial or network hardware.
- Preserve unrelated worktree changes.

---

### Task 1: Light USB consent surface and readable privacy note

**Files:**
- Create: `frontend/tests/usb-console-styles.test.ts`
- Modify: `frontend/src/styles.css:1905-1964`
- Modify: `docs/IMPLEMENTATION_STATUS.md:65,92-96`

**Interfaces:**
- Consumes: Existing `.terminal-session`, `.usb-console-settings`, `.usb-console-authorization`, and `.terminal-note` classes.
- Produces: CSS-only pre-connection presentation; no JavaScript interface changes.

- [x] **Step 1: Write the failing CSS regression test**

```typescript
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
```

- [x] **Step 2: Run the focused test and verify RED**

Run from `frontend`:

```powershell
npm.cmd test -- --run tests/usb-console-styles.test.ts
```

Expected: FAIL because the light-state rules, inset padding, 10px font, and line height are absent.

- [x] **Step 3: Add the minimal CSS**

Keep the current shared `.terminal-note` rule and add three scoped USB pre-connection rules:

```css
.terminal-session:has(.usb-console-settings) {
  border-color: var(--border);
  background: var(--surface);
}

.terminal-session:has(.usb-console-settings) .usb-console-authorization {
  color: var(--ink);
}

.terminal-session:has(.usb-console-settings) .terminal-note {
  margin: 0;
  padding: 0 9px 9px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.5;
}
```

- [x] **Step 4: Run the focused test and verify GREEN**

```powershell
npm.cmd test -- --run tests/usb-console-styles.test.ts
```

Expected: PASS, 1 test.

- [x] **Step 5: Run the existing USB component regression**

```powershell
npm.cmd test -- --run tests/usb-console-dialog.test.tsx
```

Expected: PASS; no Web Serial hardware is enumerated or opened.

- [ ] **Step 6: Verify the rendered UI**

Open the local application in the in-app browser and inspect Manual USB Console before and after the mocked/open transition. Confirm the consent surface is white, authorization text is dark, the privacy note is fully inset and readable, narrow-width wrapping is not clipped, and the connected terminal remains dark.

The in-app browser reported no available browser backend. The operator approved
continuing with automated verification; visual browser validation remains
explicitly pending in `docs/IMPLEMENTATION_STATUS.md`.

- [x] **Step 7: Record the delivered UI behavior**

Append this verification row to `docs/IMPLEMENTATION_STATUS.md`:

```markdown
| 2026-07-20 | Manual USB Console UI polish | Focused CSS regression; USB component regression; frontend type check, lint, test, and production build | Light pre-connection surface and readable inset privacy note verified; connected terminal behavior unchanged; no hardware contacted |
```

- [x] **Step 8: Run the full frontend verification**

```powershell
npm.cmd run verify
```

Expected: TypeScript, ESLint, all Vitest tests, and Vite production build pass; the existing large-chunk warning may remain.

- [x] **Step 9: Check impact and commit only scoped files**

Run repository-required GitNexus `detect_changes` for the current diff. Confirm the affected scope is limited to USB terminal presentation and documentation, then commit only:

```powershell
git add frontend/src/styles.css frontend/tests/usb-console-styles.test.ts docs/IMPLEMENTATION_STATUS.md docs/superpowers/specs/2026-07-20-usb-console-ui-polish-design.md docs/superpowers/plans/2026-07-20-usb-console-ui-polish.md
git commit -m "fix(ui): polish USB console consent"
```

GitNexus `detect-changes --scope staged` reported 5 files, 10 indexed
documentation symbols, 0 affected processes, and low risk before commit
`97a1213`.
