# Phase 4 — Multi-model AI (First Slice) Design

## 1. Context

Phase 3 built the first structured write path: a `ChangePlan`/`ChangeStep`
pipeline (`app/changes/`) for Cisco IOS/IOS-XE interface description and
admin-state changes, gated behind `structured_writes_enabled`, enforcing
Intent → Change Plan → Vendor Render → Validation → Snapshot → Diff/Risk →
User Confirmation → Device Lock → Apply → Post-check → Confirm/Rollback →
Audit end to end. Its design doc explicitly deferred AI: "AI-generated Change
Plans (Phase 4 — this phase only builds the pipeline the AI gateway will
later be restricted to producing intent for)."

`docs/network-automation-final-plan.md` §5/§9/§15 defines Phase 4 as a
LiteLLM-style multi-provider AI gateway: provider profiles, streaming,
context sanitization, read-only tools, and structured Change Plan
generation. Full scope (5 provider types, tool-calling, streaming, a chat
agent) is too large for one slice — this mirrors Phase 3's own precedent of
narrowing "Interface/VLAN/Static Route" down to an interface-only first
slice.

This spec covers only the first vertical slice of Phase 4: a **chat-first AI
assistant, single provider family (generic OpenAI-compatible endpoints,
bring-your-own-key/URL), read-only tools, and AI-drafted Change Plans that
flow through the existing, unmodified Phase 3 pipeline.**

## 2. Approved Decisions

Confirmed with the user before this design was written:

1. **No self-hosted model serving.** The application never runs or bundles
   an inference server. It is purely a gateway: the user brings their own
   `base_url` and API key (real OpenAI, a self-hosted Ollama exposing its
   OpenAI-compatible endpoint, LM Studio, OpenRouter, vLLM, etc.). One
   generic "OpenAI-compatible" adapter covers all of these without
   vendor-specific code, since they share the same wire format. Anthropic-
   and Gemini-native adapters (different wire formats) are explicitly
   deferred to a later slice.
2. **Interaction model: chat-first agent**, not a single-shot generator.
   Concept reference given by the user: an "opencode"-style assistant with
   a provider/model picker per session, matching §9's "Provider/model
   selection ต่อ Session."
3. **Confirmation model: per-session toggle between Confirm and Auto,
   user's own choice, at the user's own risk in Auto mode** — not a fixed
   always-confirm design. This was a real, deliberate relaxation the user
   asked for; see §6 for how it is bounded so it doesn't quietly break the
   pipeline's core "AI cannot skip Confirmation" invariant from §15's Phase
   4 exit criteria.
4. **Destructive-command blocklist is an unconditional floor, not subject to
   the Auto-mode risk toggle.** §7 of the final plan states "Wizard/AI block
   คำสั่ง erase, reload, format และ factory reset" with no mode exception.
   Auto mode changes who clicks Apply/Send; it does not change what is
   allowed to be sent.
5. **AI client library: official `openai` Python SDK** pointed at the
   user's configured `base_url`, over hand-rolled `httpx` calls or pulling
   in `litellm`. See §4.1 for the three options considered.
6. **AI-drafted Change Plans reuse `app/changes/service.py` verbatim** — no
   parallel or looser validation path. A `source` field distinguishes
   `"manual"` from `"ai_generated"` for audit only; it does not change
   pipeline behavior.

## 3. Scope

### In scope

- `ProviderProfile` model, encrypted API key storage (mirrors
  `CredentialProfile`'s `encrypted_secret` / AES-256-GCM pattern), base URL,
  model ID, context-limit override, capability flags populated by an
  explicit "test connection / capability probe" action
- `AssistantSession` (provider profile, mode, timestamps) and
  `AssistantMessage` (role, content, tool calls/results) persisted to
  Postgres
- OpenAI-compatible client wrapper around the official `openai` SDK:
  chat completion, streaming, tool-calling (feature-detected per profile)
- Read-only tool set wrapping existing endpoints only: device facts,
  interfaces, neighbors/topology, snapshots list, events list
- Context sanitizer: strips credential/secret fields from tool results
  before they enter model context (extends the existing "secrets never
  leave the server" boundary in `docs/safety-model.md` §"Secret rules" to
  cover AI context explicitly)
- AI-drafted `ChangePlan` creation through the existing Phase 3 service,
  tagged `source="ai_generated"`
- AI-drafted Direct Mode console command suggestions, relayed to a live
  terminal session only through a backend action that enforces the
  destructive-command blocklist first
- Confirm/Auto mode toggle per `AssistantSession`: Confirm is the default
  and the state every new session starts in; switching to Auto requires an
  explicit one-time risk acknowledgment (same pattern as the existing
  Direct Mode warning) and is bounded by a max-auto-applies-per-session cap
  before it demands re-acknowledgment
- `ai_gateway_enabled` kill switch (off by default), matching the
  `analysis_enabled` / `telnet_enabled` / `structured_writes_enabled`
  pattern in `app/core/config.py`
- New "Assistant" nav item; chat UI reusing the existing Configure-tab
  diff/risk card for AI-proposed Change Plans and a code-block-with-button
  pattern for console suggestions
- Fixture/fake-backed automated tests only for this slice (no real-provider
  API calls in routine tests, matching how real-lab/real-device tests are
  opt-in elsewhere in this project)

### Out of scope (this slice)

- Anthropic, Gemini, and native-Ollama adapters (different wire formats;
  Ollama is still reachable today via its own OpenAI-compatible endpoint)
- VLAN access/trunk and static route Change Plan generation — Phase 3 never
  built those renderers, so AI's structured-apply capability is bounded to
  whatever Phase 3 supports today (interface admin-state/description).
  Anything beyond that is a Direct Mode console suggestion, not a
  structured Change Plan.
- Any write-capable tool given to the model, in either mode
- Multi-hop autonomous remediation as a distinct planning feature (the
  user's original capability #2 — "see the whole topology and configure
  each hop to reach an unreachable device"). This slice gives the AI
  read access to topology and the ability to draft/relay changes one
  device at a time; it does not add path-computation or
  batched-multi-device-plan orchestration logic. Revisit as a fast-follow
  slice once single-device AI-assisted changes are proven.
- A persistent cross-session Auto-mode default
- Chat session sharing/collaboration between users (this remains a
  single-user local application)
- Non-Cisco AI-assisted changes (bounded by the same vendor scope Phase 3
  already has)

## 4. Architecture

### 4.1 Why the official `openai` SDK

Three options were considered for the provider client:

**A — hand-rolled `httpx` client** (matches the backend's existing
minimal-dependency-only pattern: it currently depends on `httpx` and
nothing else for HTTP). Full control, but requires reimplementing SSE
streaming parsing, retry, and the OpenAI tool-calling JSON schema by hand
for no real benefit, since the wire format being implemented *is* the
OpenAI shape either way.

**B — `litellm` package.** Provides multi-provider normalization out of the
box, which would pay off if/when Anthropic/Gemini-native adapters are
added. Rejected for this slice: it pulls in a heavy transitive dependency
tree for four provider integrations (Anthropic, Gemini, Ollama-native,
generic) this slice does not use, working against this codebase's
consistently minimal dependency footprint.

**C — official `openai` Python SDK, pointed at a custom `base_url` (chosen).**
This is the standard, documented way OpenAI-compatible endpoints (Ollama,
LM Studio, OpenRouter, vLLM, etc.) are already meant to be consumed — the
SDK accepts `base_url` and `api_key` directly. It provides streaming,
tool-calling schema helpers, and retry behavior maintained upstream by
OpenAI, at the cost of exactly one new, narrowly-scoped, well-maintained
dependency. When Anthropic/Gemini-native adapters are added in a later
slice, each becomes its own thin adapter behind the same internal
`ProviderClient` interface — this choice does not block that.

### 4.2 Module layout

New `backend/app/assistant/` module, mirroring the existing `app/changes/`
and `app/analysis/` shape: pure-logic types → provider client → service
orchestration (chat turn handling, tool dispatch, Change Plan handoff) →
repository → schemas → API router. The router only ever calls into
`app/changes/service.py` to create a Change Plan — it does not duplicate or
reimplement any part of that pipeline.

Frontend: new `frontend/src/features/assistant/` following the existing
feature-folder convention (see `features/inventory/`, `features/topology/`),
with a `ProviderProfile` management modal cloned from the existing
`CredentialProfile` modal.

## 5. Data model

**`ProviderProfile`** — `id`, `name`, `base_url`, `encrypted_api_key`
(nullable — no-key local mode is a valid configuration), `model_id`,
`context_limit_override` (nullable), `supports_streaming`,
`supports_tool_calling` (both populated by the capability-probe action, not
assumed), timestamps.

**`AssistantSession`** — `id`, `provider_profile_id` (FK), `mode`
(`confirm` | `auto`, default `confirm`), timestamps. Named `AssistantSession`
rather than `Session` to avoid collision with the application's own
master-password auth session.

**`AssistantMessage`** — `id`, `session_id` (FK), `role` (`user` |
`assistant` | `tool`), `content`, `tool_calls`/`tool_results` (JSON,
nullable), `created_at`.

**`ChangePlan.source`** — new column on the existing Phase 3 model,
`"manual" | "ai_generated"`, default `"manual"`. Audit-only; no branch in
`app/changes/service.py` reads this field to alter validation, risk, or
apply behavior.

## 6. Safety enforcement

- The tool schema handed to the model contains only read wrappers around
  existing GET endpoints (facts, interfaces, neighbors, snapshots, events).
  No write tool exists in this slice's tool registry — there is nothing to
  gate by mode because it is simply never registered.
- Tool results are passed through the same credential-scrubbing boundary
  the rest of the app already enforces before they're serialized into
  model context. `docs/safety-model.md` §"Secret rules" gets a line added
  during implementation: AI context and tool results join the existing list
  of places secrets must never appear (logs, event detail, diff text,
  screenshots, exception messages, test artifacts, fixtures).
- An AI-drafted Change Plan is created by calling
  `app/changes/service.py` directly — the same function a human-initiated
  request calls. There is no separate "AI apply" code path to audit
  separately; auditing the one path Phase 3 already tests is sufficient.
- Direct Mode console suggestions are drafted as chat content only. Relaying
  a suggested command into a live terminal session always passes through a
  backend action that checks the destructive-command blocklist
  (`erase`/`reload`/`format`/`factory reset`) first, in both modes. Confirm
  mode additionally requires a per-command human click before that action
  ever runs; Auto mode calls it immediately after the blocklist check.
- **Confirm mode** (default, and what every new `AssistantSession` starts
  in): every Change Plan Apply and every console command relay requires an
  explicit per-action click — this is the existing UI behavior, unchanged.
- **Auto mode**: opt-in per session, gated behind a one-time explicit risk
  acknowledgment (mirroring the existing Direct Mode warning pattern), and
  bounded by a configurable max-auto-applies-per-session counter that,
  once reached, forces the session back to requiring re-acknowledgment
  before continuing. This bounds the blast radius of a misbehaving or
  looping model in the same spirit as this project's other bounded
  operations (`ANALYSIS_MAX_DEVICES`, bounded discovery scanning).
- Auto mode is never a persisted cross-session default; every new session
  starts in Confirm mode regardless of what the previous session used.

## 7. Frontend UX

New "Assistant" item in the `AppShell` sidebar nav, alongside
Inventory/Topology/Analysis. Provider profile CRUD reuses the existing
Credential-profile list/create/edit/delete modal pattern verbatim structurally
(new copy and fields, same interaction shape) — including a "Test
connection" action that runs the capability probe. The chat page itself: a
session list, the active transcript, an input box, a provider/model picker,
and the Confirm/Auto toggle (with the risk-acknowledgment modal appearing
the first time a session switches to Auto). An AI-proposed Change Plan
renders as a card inside the transcript, reusing the existing Configure-tab
diff/risk component rather than a new one. An AI-proposed console command
renders as a code block with a "Send to terminal" button in Confirm mode,
or a "Sent" status line in Auto mode after the blocklist-checked relay.

## 8. Testing

- Provider client: unit tests against a mocked `openai` SDK/HTTP layer
  covering chat completion, streaming, and tool-calling — no real provider
  network calls in routine tests, matching how real-device/real-lab tests
  are opt-in elsewhere in this project.
- A test proving the tool schema sent to the model never contains a write
  tool, regardless of mode.
- A test proving the destructive-command blocklist rejects a relay attempt
  in Auto mode exactly as it does in Confirm mode.
- Phase 3's existing Change Plan validation tests parametrized with
  `source="ai_generated"`, proving no separate or looser path exists for
  AI-originated plans.
- A frontend test for the mode toggle: Auto is unreachable without passing
  through the risk-acknowledgment step, and a fresh session always renders
  as Confirm regardless of the previous session's mode.

## 9. Open questions / risks

- **Tool-calling support varies across "OpenAI-compatible" endpoints.** Not
  every compatible server implements the `tools` parameter. This is why
  `supports_tool_calling` is a probed capability flag, not an assumption —
  when false, the assistant falls back to a plain chat session with no tool
  access rather than failing outright.
- **Auto-mode cap value** (max auto-applies before forced re-acknowledgment)
  is not yet fixed; propose a small default (e.g. 5) and make it operator-
  configurable, to be settled during planning.
- **`docs/safety-model.md` needs a follow-up edit** during implementation to
  formally document the AI-context secret boundary and the Auto-mode
  acknowledgment/cap mechanism, matching how Phase 3's structured-write
  rules are already documented there.
