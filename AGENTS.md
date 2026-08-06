# Repository guidance for coding agents

## Source of truth

Read `docs/network-automation-final-plan.md` in full before changing product
behavior. Preserve that final plan unchanged unless the user explicitly asks to
revise it. Record delivered behavior in `docs/IMPLEMENTATION_STATUS.md` and
vendor evidence in `docs/CAPABILITY_MATRIX.md`.

## Safety invariants

- Treat all network targets as real devices. Never infer permission to connect,
  scan, configure, reload, or erase a device.
- Routine automated tests must not contact a network device. Real-lab tests are
  separately marked, skipped by default, and require the opt-ins documented in
  `docs/lab-test-guide.md`.
- All device write capabilities are **Not Implemented** in phases 0–1. Do not
  add a write path under the label of a read-only change.
- Never log or commit credentials, private keys, raw unsanitized configuration,
  session cookies, provider keys, or generated `.secrets` files.
- Keep the normal Compose exposure on `127.0.0.1`; a broader bind is an explicit
  operator decision that requires the review in `docs/safety-model.md`.
- Preserve immutable snapshot semantics. Do not mutate an observed running
  configuration in place.
- Unknown or unverified vendor behavior fails closed to Safety Level D
  (read-only).

## Repository map

- `backend/`: FastAPI, RQ worker, migrations, drivers, and backend tests
- `frontend/`: React/Vite UI, reverse proxy image, and frontend tests
- `deploy/`: Compose definitions and non-destructive bootstrap scripts
- `docs/`: architecture, operations, safety, capability evidence, and status

Do not duplicate reverse-proxy routing in `deploy/`; the frontend image owns its
Nginx configuration. The API and worker must continue using the same backend
image with different commands.

## Local workflow

```text
python deploy/init-secrets.py
docker compose -f deploy/compose.yml config --quiet
docker compose -f deploy/compose.yml up --build --detach --wait
```

Use `.env.example` only for non-secret settings. The initializer is deliberately
non-rotating. Never replace `master.key` during an upgrade or test run.

Before handing off a change, run the relevant formatter, lint, type check, and
tests in both affected packages. Validate Compose with `docker compose config`
and keep documentation status conservative: implementation without fixture and
lab evidence is not `Supported`.

## Change discipline

- Prefer vertical slices with explicit error, timeout, and disconnected-state
  tests.
- Keep capability declarations separate from vendor driver implementation.
- Sanitize fixtures and use documentation-range addresses and fake hostnames.
- Do not introduce optional platforms, bulk writes, autonomous agents, or cloud
  deployment onto the phase 0–1 critical path.
- Preserve unrelated user changes in a dirty worktree.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Terraformer** (2854 symbols, 5814 relationships, 180 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/Terraformer/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Terraformer/clusters` | All functional areas |
| `gitnexus://repo/Terraformer/processes` | All execution flows |
| `gitnexus://repo/Terraformer/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
