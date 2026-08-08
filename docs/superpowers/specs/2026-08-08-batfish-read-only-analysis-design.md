# Batfish Read-Only Configuration Analysis Design

**Status:** Approved for implementation planning

**Date:** 2026-08-08

**Scope:** Add an optional, read-only network analysis capability that answers
four operator questions from configuration snapshots the application already
stores. No structured write path, no device emulation, no new device capability.

## 1. Context

The product concept is a "playground": networking should feel easy and should
let an operator try things without fear of breaking something. Two properties
follow from that, and both were confirmed as the intent of this work:

1. An easy, visual path to doing things — no CLI memorisation.
2. A safe way to be wrong — see what a change does before it reaches hardware.

The second property is what this design serves. Batfish answers questions about
a network by reasoning over device configurations, without sending a packet or
touching a device.

This work was selected ahead of Phase 3 (Safe Configuration MVP) deliberately.
Every other requested capability — Ansible/Nornir orchestration, ZTP, IaC export
— depends on a structured write path that does not exist yet. Batfish does not:
Phase 1 already delivers immutable running-config snapshots, so this capability
can ship against data the application holds today.

Sequencing it first also de-risks Phase 3. The intended long-term shape is for
Batfish to become the "what-if" step inside the Phase 3 apply pipeline
(`Intent → Change Plan → Vendor Render → Validation → Snapshot → Diff/Risk →
Confirmation → Apply`). Making a mandatory pipeline gate out of a component
whose ability to parse this application's snapshots is unproven would be a bad
bet. This spec proves the integration on read-only data first.

`docs/network-automation-final-plan.md` is unchanged by this design. The plan
lists Batfish under Future/Optional (§5) and Phase 8 (§15); this work brings the
read-only subset forward without altering the phase definitions.

## 2. Approved Decisions

- Batfish runs as an **optional Compose profile, disabled by default**. The
  documented resource floor (4 cores / 8 GB) is unchanged for operators who do
  not enable it.
- The analysis network snapshot is assembled from the **latest configuration
  snapshot of every registered device**, with an explicit re-parse action. The
  operator does not hand-pick devices.
- **Only sanitized configuration** is sent to Batfish, via the existing
  `SnapshotService.get_sanitized_content()` accessor.
- Analysis runs as an **RQ job**, following the existing diagnostics pattern.
- **Cisco IOS/IOS-XE only** in this iteration. Fortinet FortiOS and generic
  devices are excluded and reported as exclusions, not silently dropped.
- Results are labelled **`INFERRED`** without exception, per final-plan §6.
- A **completeness disclosure is mandatory** on every result surface.
- Architecture is **parse once, query many**: a slow initialisation job followed
  by fast interactive queries against the parsed snapshot.

## 3. Scope

### In scope

Four questions, chosen because the expensive part of this work is the
integration (snapshot assembly, container lifecycle, parsing), not the
individual queries. Once a snapshot is parsed, each question is a different
query over the same data.

| # | Operator question | Batfish question | Result lifetime |
|---|---|---|---|
| 1 | Why can A not reach B? | `traceroute` | Ephemeral |
| 2 | What is broken in my configuration? | `initIssues`, `undefinedReferences`, `unusedStructures` | Persisted |
| 3 | What does this ACL actually do? | `testFilters`, `filterLineReachability` | Ephemeral |
| 4 | Does my configuration match my cabling? | `interfaceProperties`, `switchedVlanProperties` checked against stored CDP/LLDP records | Persisted |

Questions 2 and 4 are by-products of parsing and are persisted as findings.
Questions 1 and 3 are interactive and are not persisted; only the fact that they
were asked is audited.

### 3.1 Observed neighbours are an input, not only a comparison

Batfish accepts a layer-1 topology as snapshot input
(`batfish/layer1_topology.json`). The stored CDP/LLDP records are exactly that
data, so they are **supplied to the snapshot** rather than only diffed against
it. Without a layer-1 topology, Batfish infers adjacency from addressing, which
is weak on a switched campus where most access ports carry no layer-3 address.
Supplying observed neighbours is what makes question 1 trustworthy here.

This corrects an earlier framing of question 4 as a diff of Batfish
`layer3Edges` against CDP/LLDP. Those are not comparable: CDP/LLDP report
layer-2 neighbour and interface pairs, while `layer3Edges` reports routed
adjacencies. On a campus most observed links are not layer-3 edges, so that
comparison would report large numbers of false differences.

Question 4 is therefore scoped to differences that are genuinely detectable at
this boundary:

- An interface named in a CDP/LLDP record does not exist in the parsed
  configuration of that device.
- The two ends of an observed link disagree on switchport mode (access versus
  trunk) or on access VLAN.

Both are the real-world fault the question exists to catch: cabled one way,
configured another. Anything requiring knowledge the application does not hold
is out of scope rather than approximated.

### Out of scope

- Any structured write, apply, or change-plan path. Safety Level D is unchanged.
- Device emulation. This design analyses configuration text; it does not run
  virtual devices. GNS3/EVE-NG remain external tools the operator drives
  themselves.
- BGP/OSPF adjacency analysis.
- Differential analysis between two snapshots.
- A custom Batfish question editor.
- Vendors other than Cisco IOS/IOS-XE.

## 4. Architecture

### 4.1 Container and trust boundary

A new profile-gated Compose file, `deploy/compose.analysis.yml`:

```text
batfish (batfish/allinone)
  networks: [analysis]      # internal: true
  ports:    none            # not reachable from the host
  secrets:  none            # no master key, no database password

api, worker
  networks: [..., analysis]
```

The `analysis` network is declared `internal: true`. This is a deliberate
difference from the existing `application` network, which retains outbound
routing because the worker must reach approved management-network devices.
Batfish has no reason to reach a device or the internet: it receives
configuration text and returns findings. The network is closed at creation
rather than relied upon to be unused.

Batfish receives no secrets and holds no credentials.

### 4.2 Backend module

New package `backend/app/analysis/`:

| File | Responsibility |
|---|---|
| `client.py` | The only module that knows Batfish exists. Wraps `pybatfish`. |
| `snapshot_builder.py` | Assembles the sanitized configuration set and classifies every registered device as included or excluded. |
| `questions.py` | Maps the four questions to typed results. No `pandas` object or Batfish type crosses this boundary. |

New API module `backend/app/api/analysis.py`. New job type
`JobType.ANALYZE_NETWORK`.

### 4.3 Settings

`ANALYSIS_ENABLED`, default `false`, following the `TELNET_ENABLED` pattern
established in `backend/app/core/config.py`.

### 4.4 Dependency handling

`pybatfish` transitively requires `pandas` and `numpy` (roughly 80 MB), which
would otherwise sit in the always-on backend image even when analysis is
disabled. It is therefore declared as an **optional dependency group**, and
imported lazily inside `analysis/client.py`. The codebase already uses this
pattern: `ScrapliTransport.__init__` imports Scrapli at call time rather than at
module import.

If the import fails, the API returns the typed error `analysis_unavailable`
rather than failing to start. Analysis is unavailable; the application is not.

## 5. Data model

Three new tables, added by one migration.

### `analysis_snapshots`

One row per parse operation.

| Column | Notes |
|---|---|
| `id` | UUID primary key; also used as the Batfish snapshot name |
| `status` | `pending` / `parsing` / `ready` / `failed` / `expired` |
| `device_count` | Devices whose configuration was included |
| `oldest_config_at` | Age of the oldest configuration in the set |
| `newest_config_at` | Age of the newest configuration in the set |
| `parse_warning_count` | Count of parse findings |
| `findings_truncated` | Set when the findings cap was reached |
| `failure_code` | Sanitized failure code when `status = failed` |

### `analysis_snapshot_members`

One row per device that was **registered at analysis time** — not only the
devices that were included.

| Column | Notes |
|---|---|
| `analysis_snapshot_id` | Foreign key, cascade delete |
| `device_id` | Foreign key |
| `config_snapshot_id` | Nullable; null when the device was excluded |
| `exclusion_reason` | Nullable: `no_snapshot` / `unsupported_vendor` |

Recording exclusions as data rather than recomputing them means the completeness
disclosure is queryable, and the snapshot is a record of what was considered and
what was left out. It also supplies the exact configuration set needed to
re-parse without contacting any device.

### `analysis_findings`

| Column | Notes |
|---|---|
| `analysis_snapshot_id` | Foreign key, cascade delete |
| `category` | `parse_warning` / `undefined_reference` / `unused_structure` / `topology_drift` |
| `severity` | Reuses `EventSeverity` |
| `device_id` | Nullable; some findings are network-wide |
| `structure_type` | e.g. `ipv4 access-list` |
| `structure_name` | Nullable |
| `detail` | Sanitized and length-capped |
| `line_number` | Nullable |

`detail` must pass through `sanitize_text` before storage. Batfish quotes the
offending configuration line in its parse warnings. The configuration sent to
Batfish is already sanitized, so this is defence in depth rather than the only
control, but it is cheap and the failure mode it prevents — a secret surfacing in
a findings list — is exactly what the safety model forbids.

## 6. Flows

### 6.1 Initialise (RQ job)

```text
POST /api/analysis-snapshots  ->  202 Accepted + JobView
```

Worker steps:

1. List every registered device.
2. Resolve the latest `config_snapshot` per device; classify each device as
   included, `no_snapshot`, or `unsupported_vendor`.
3. For included devices, call `SnapshotService.get_sanitized_content()`.
4. Build `batfish/layer1_topology.json` from stored CDP/LLDP `neighbors`,
   restricted to links whose both ends are included devices.
5. Upload the configuration set and the layer-1 topology to Batfish under the
   `analysis_snapshots.id` name.
6. Run `initIssues`, `undefinedReferences`, `unusedStructures`,
   `interfaceProperties`, `switchedVlanProperties`.
7. Persist members and findings. Derive `topology_drift` findings per §3.1:
   CDP/LLDP interfaces absent from the parsed configuration, and observed links
   whose ends disagree on switchport mode or access VLAN. Set `status = ready`.

The UI polls the job exactly as it does for diagnostics.

### 6.2 Query (synchronous)

```text
POST /api/analysis-snapshots/{id}/queries   { type, params }
```

The snapshot is already parsed, so this returns in roughly a second.

### 6.3 Expired snapshots

Batfish stores parsed snapshots inside its own container. Restarting the
container loses them.

When a query finds the snapshot missing, the API sets `status = expired` and
returns the typed error `analysis_snapshot_expired`. It does **not** re-parse
inside the request: parsing a campus takes minutes, and hiding work of that
length inside a synchronous request is a trap.

The UI surfaces a **Re-parse** action instead, which enqueues the
initialisation job using the configuration set already recorded in
`analysis_snapshot_members`. No device is contacted.

## 7. Trust model and labelling

Final-plan §6 requires every result to be labelled `Observed` or `Inferred`.
Batfish reasons over configuration, so **every result from this feature is
labelled `INFERRED`**. This composes with the existing `OBSERVED` label on
CDP/LLDP records and `UNVERIFIED` on manual links.

Batfish answers only from the configurations it is given. Supplied three of ten
switches, it will still report "A cannot reach B" with complete confidence. A
completeness disclosure is therefore rendered with every result, implemented in
a shared component so a new surface cannot omit it:

```text
Analysed 7 of 12 registered devices
  - 3 have no configuration snapshot      [Capture now]
  - 2 run a vendor that is not supported
  - Oldest configuration is 6 days old
  - 9 observed links supplied as layer-1 topology
```

The observed-link count belongs in the disclosure because reachability accuracy
depends on it. An analysis with no layer-1 topology is materially weaker than one
with it, and the operator must be able to see which they are looking at.

Result copy must never assert that a network is correct. "No findings within the
analysed scope" is permitted; "your network is healthy" is not.

Question 4 is a comparison between `INFERRED` topology derived from
configuration and `OBSERVED` topology from CDP/LLDP. Both sides already carry
their own label, and the difference between them is the finding: a link that is
cabled one way and configured another.

## 8. Input validation, error handling, and limits

### 8.1 Input validation

Questions 1 and 3 accept IP addresses. They reuse the exact-IPv4 validation
already applied to the ping/traceroute diagnostic; hostnames, CIDR ranges, and
special-use addresses are rejected. Source and destination devices are selected
from registered devices rather than typed, which is both easier and removes a
free-text input.

### 8.2 Error handling

Every path is typed and fails closed, following `backend/app/drivers/ssh_errors.py`.

| Condition | Result |
|---|---|
| `ANALYSIS_ENABLED` is false | 403 `analysis_disabled_by_policy` |
| `pybatfish` not installed | 503 `analysis_unavailable` |
| Analysis profile not started | 503 `analysis_backend_unavailable`, with the command to start it |
| No device has a snapshot | 422 `analysis_no_configs`; no empty snapshot is created |
| Batfish fails to parse anything | Job fails; `status = failed` with a sanitized `failure_code` |
| Batfish parses some devices | `status = ready`. Per-device parse failures become findings and exclusions. The job does not fail. |
| Snapshot missing after restart | 409 `analysis_snapshot_expired` |
| Query exceeds its timeout | Typed timeout error |

Partial success is the important case: a campus will contain a device whose
configuration Batfish cannot fully parse, and failing the whole analysis for it
would make the feature unusable.

### 8.3 Limits

Parsing a campus is CPU- and memory-intensive, so the same admission discipline
already applied to discovery is applied here.

- **One active analysis job at a time**, matching the existing "one active scan
  at a time" rule for discovery.
- Maximum 200 devices per snapshot, matching the Stage B ceiling in the plan.
- Maximum 1,000 persisted findings per snapshot, with `findings_truncated` set
  when the cap is reached.
- Query timeout 30 seconds; parse timeout 10 minutes.
- Retention: the 10 most recent analysis snapshots are kept; older rows are
  deleted and their findings cascade. The plan lists unbounded disk growth as an
  acceptance risk.

## 9. Testing

- **Fake Batfish client**, following the `FakeTransportFactory` pattern, so CI
  requires no container.
- **Golden fixtures**: sanitized Batfish JSON responses per question, driving
  parser tests. This mirrors the existing sanitized CLI fixture approach.
- **Integration tests** over the full API flow with the fake client: create,
  poll, query, expired path, disabled path, partial-parse path.
- **Security tests**, which this repository weights heavily:
  - The configuration handed to the fake client contains no raw secret. Drive
    this from a fixture containing `snmp-server community` and an enable secret,
    and assert both are redacted.
  - `analysis_findings.detail` is sanitized.
  - Every endpoint fails closed when `ANALYSIS_ENABLED` is false.
  - Every result response carries completeness data.
  - Batfish receives no credential material.
- **Migration tests** extend the existing `test_migrations.py`, which now
  executes the chain and asserts `alembic check` is clean, including against
  real PostgreSQL when `TEST_POSTGRES_URL` is set.
- **Opt-in real-Batfish test**, marker `analysis`, requiring
  `RUN_ANALYSIS_TESTS=1` and a running container — the same shape as the
  existing `lab` marker.

## 10. Success criteria

1. With the analysis profile stopped, every analysis endpoint returns a typed
   error and no other application behaviour changes.
2. With the profile running, an analysis snapshot is built from stored
   configuration snapshots, and the completeness disclosure reports the correct
   included and excluded counts.
3. Findings for questions 2 and 4 are persisted, sanitized, and attributable to
   a device where applicable.
4. A `traceroute` query against a parsed snapshot returns a hop list and a
   disposition, and identifies the device and ACL line responsible for a drop.
   The snapshot used for this must include a layer-1 topology derived from
   stored CDP/LLDP records, and the observed-link count must appear in the
   completeness disclosure.
5. Restarting the Batfish container yields `analysis_snapshot_expired` and a
   working Re-parse action that contacts no device.
6. **A recorded run against real Cisco IOS/IOS-XE configuration** — a GNS3 or
   EVE-NG node is sufficient — confirms Batfish parses configuration captured by
   this application. This is the reason the work was sequenced ahead of Phase 3
   and is required for the spec to be considered delivered.

## 11. Follow-on work

Recorded here for sequencing only; each requires its own spec.

| Sub-project | Depends on |
|---|---|
| Phase 3 Safe Configuration MVP, with Batfish as the what-if validation step | This spec |
| Intent / IPAM layer (sites, roles, address pools) | Independent |
| Bulk operations at campus scale (Nornir) | Phase 3 |
| ZTP | Phase 3 and the intent layer |
| Ansible / YAML export | Phase 3 |
