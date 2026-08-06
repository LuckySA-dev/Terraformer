# Phase 1–2 Readiness, Local Lab Providers, and Phase 3 Pilot Design

**Status:** Approved for implementation planning

**Date:** 2026-08-06

**Scope:** Close Phase 1–2 functional gaps, support EVE-NG/GNS3 as local-lab
targets and read-only topology providers, then deliver one bounded Phase 3
structured-write pilot for Cisco interface descriptions.

## 1. Context

The application can connect to an authorized physical Cisco lab device, but a
successful connection does not prove that every Phase 1–2 user flow is complete.
The repository still records several capabilities as lab-unverified, and the
latest application commit has not been rerun through the full physical and
virtual acceptance flows.

The next work must therefore close the Phase 1–2 foundation before expanding
structured writes. Local EVE-NG and GNS3 environments will provide repeatable
multi-node coverage, while physical hardware remains the primary product target.
Virtual and physical devices must use the same device driver and change pipeline;
there will be no emulator-only configuration behavior.

This design preserves `docs/network-automation-final-plan.md` unchanged.

## 2. Approved Decisions

- Phase 1–2 functional readiness is completed before the Phase 3 pilot.
- The readiness audit covers functional flows, error guidance, responsive layout,
  keyboard/focus behavior, and accessibility that blocks use. Cosmetic polish,
  theme redesign, and animation are excluded.
- Current `main` is rerun against the authorized lab; prior results are context,
  not current-build evidence.
- The physical lab currently has one Cisco device. It can validate single-device
  reads, snapshots, terminal, and diagnostics, but cannot validate a physical
  CDP/LLDP link.
- EVE-NG/GNS3 will provide at least two virtual Cisco nodes for multi-node
  discovery and topology acceptance. Virtual evidence never substitutes for a
  physical-device capability claim.
- EVE-NG/GNS3 integration includes normal SSH device access and read-only REST
  topology import.
- Imported nodes are observed placeholders. A user explicitly binds each
  placeholder to an existing registered device; import never creates inventory.
- Provider profiles are encrypted and separate from device credential profiles.
- External topology polling runs only while the Topology page is mounted. The
  default interval is 60 seconds and the allowed range is 30–300 seconds.
- The first Phase 3 capability is setting or clearing one Cisco interface
  description.
- Every registered Cisco device that passes the normal connection and trust
  gates can use the pilot. There is no global Lab Mode and no separate
  virtual-device execution path.
- Apply requires Preview, an immutable snapshot, diff and risk display, exact
  device-name confirmation, and a device/plan-scoped one-time Maintenance Code.
- A Maintenance Code lasts 15 minutes, is single-use, and is never persisted or
  logged in plaintext.
- The pilot changes running-config only. It never sends `write memory`,
  `copy running-config startup-config`, or an equivalent save command.
- Post-check failure produces Assisted Rollback guidance. Rollback is never
  automatic and requires a fresh Preview, confirmation, and Maintenance Code.
- First-contact SSH trust displays the fingerprint for explicit operator
  confirmation and then pins the key per device. Unknown and changed keys never
  receive automatic trust.
- Provider HTTPS uses normal certificate verification or an explicitly pinned
  certificate. HTTP is allowed only for an exact loopback/private target after a
  visible insecure-transport acknowledgment.

## 3. Delivery Sequence

### Milestone A: Phase 1–2 readiness closure

1. Build a conformance matrix from the final plan, implementation status,
   capability matrix, code, tests, and current lab evidence.
2. Classify each finding:
   - **P0:** security, data-loss, trust-boundary, or connection blocker;
   - **P1:** missing Phase 1–2 exit-criteria behavior;
   - **P2:** cosmetic, optional, or post-MVP work.
3. Fix P0 and P1 findings as bounded vertical slices. Do not implement P2 work.
4. Run automated verification without opening a lab connection.
5. Run separately authorized current-build acceptance against the physical
   single-device lab and a virtual multi-node lab.
6. Record only sanitized validation metadata and keep unsupported claims
   conservative.

### Milestone B: local-lab provider integration

1. Add encrypted EVE-NG and GNS3 provider profiles.
2. Probe provider type/version/capabilities using read-only endpoints.
3. Import one selected project's nodes, links, and positions.
4. Normalize the external data into observed provider topology records.
5. Let the operator bind an observed node to a registered inventory device.
6. Refresh while the Topology page is open and retain the last successful view
   as stale after a refresh failure.

### Milestone C: Phase 3 interface-description pilot

1. Create and preview an immutable interface-description `ChangePlan`.
2. Capture the pre-change running configuration as an immutable snapshot.
3. Render and validate the exact Cisco commands and assisted rollback commands.
4. Display diff, risk, safety level, target, and persistence boundary.
5. Require the exact stored device name and one-time Maintenance Code.
6. Recheck current state, acquire the per-device write lock, and apply.
7. Post-check the exact interface description.
8. Report success or produce an Assisted Rollback plan.

Full VLAN, trunk, SVI, static-route, AI, and bulk-write work begins only after
these milestones pass their exit gates.

## 4. Phase 1–2 Readiness Model

The readiness artifact must contain one row per final-plan requirement with:

- phase and requirement;
- backend implementation status;
- frontend user-flow status;
- automated test evidence;
- virtual-lab evidence;
- physical-lab evidence;
- gap classification and owner;
- conservative capability status.

The audit distinguishes three states that must not be collapsed:

- missing implementation;
- implementation present but missing automated evidence;
- automated verification passed but hardware validation pending.

### Physical single-device acceptance

The authorized physical run covers only capabilities the available topology can
prove:

- manual add and explicit connection test;
- host-key enrollment and subsequent pinned-key connection;
- facts and interface inventory;
- immutable running-config snapshot;
- SSH terminal open, input, disconnect, cleanup, and retry guidance;
- allowlisted diagnostics;
- sanitized event and application-log behavior.

It must not claim physical CDP/LLDP link validation with only one device.

### Virtual multi-node acceptance

An EVE-NG or GNS3 project with at least two virtual Cisco nodes covers:

- bounded discovery and explicit approval;
- CDP/LLDP neighbor collection;
- observed node/link projection and interface-pair labels;
- topology refresh and stale-state behavior;
- terminal and diagnostics across multiple registered nodes;
- external-provider import and manual binding.

Evidence records identify the device category as virtual. They do not promote
physical model or OS support.

## 5. Local-Lab Connectivity

Terraformer remains bound to `127.0.0.1` by default. Local-lab support changes
outbound reachability, not the application's inbound exposure.

The supported topologies are:

- EVE-NG/GNS3 in a VM on the same host as Docker Desktop;
- EVE-NG/GNS3 on another host or VM in the management LAN.

Same-host documentation provides explicit examples for an address reachable
from the backend containers, including `host.docker.internal` only when the
emulator service is actually published on the host. Management-LAN use requires
an exact provider/device address and existing host routing. Terraformer does not
create host routes, firewall rules, bridges, TAP devices, emulator clouds, or
NAT rules.

A provider/device preflight reports sanitized phases such as DNS resolution,
route unavailable, TCP unavailable, TLS trust required, SSH host-key approval
required, authentication failed, or provider schema unsupported. It never
performs a subnet scan or silently switches transports.

## 6. SSH Host-Key Trust

Host-key verification is mandatory for both structured reads/writes and the SSH
terminal.

For first contact, the application may collect the offered public host key
without authenticating or running a command. The UI displays the algorithm and
fingerprint and warns the operator to compare it through the lab's established
channel. Trust is persisted only after an explicit confirmation for the exact
device.

The pinned trust record contains:

- device identifier;
- host-key algorithm;
- public key or canonical known-hosts material;
- fingerprint;
- confirmation timestamp;
- confirming local actor.

It contains no credential or session content. A later unknown or changed key
fails closed with a sanitized result. There is no automatic replace, ignore,
fallback, or global weakening. Provider API certificate pins are separate from
device SSH host keys.

## 7. Provider Profiles and Read-Only Import

### Provider profile

Each provider profile stores:

- display name;
- provider type: `eve_ng` or `gns3`;
- normalized base URL;
- encrypted username/password;
- transport mode: verified TLS, pinned TLS, or acknowledged private HTTP;
- optional pinned certificate fingerprint;
- poll interval from 30–300 seconds;
- last sanitized connection result and detected provider version.

Secrets reuse the existing application encryption boundary but remain in a
separate provider-profile record. Provider passwords never enter device
credential profiles or frontend responses.

### Network boundary

At profile creation and immediately before each request, the backend validates
the scheme, exact host, resolved addresses, port, and transport mode. Loopback
and private addresses are allowed; public, multicast, unspecified, and broadcast
targets are rejected for this local-lab slice. Redirects are disabled. A
hostname whose resolution leaves the allowed address set fails closed.

HTTP requires a per-profile acknowledgment because API credentials would cross
the local network without TLS. TLS verification is the default. A self-signed
lab endpoint uses an explicitly confirmed certificate fingerprint rather than
`verify=False`.

### Provider adapters

Adapters expose only:

- connection/version probe;
- project listing;
- selected-project node listing;
- selected-project link listing.

EVE-NG authentication cookies remain in memory for one bounded request session
and are discarded after logout/cleanup. GNS3 authentication is sent without
placing credentials in the URL. Raw provider responses, cookies, and exceptions
are never persisted or returned directly.

Only allowlisted GET operations are implemented. Terraformer does not start,
stop, suspend, reload, create, update, or delete emulator objects.

### Normalized external topology

The normalized records use a stable provider/profile/project/node or link key
and contain only the minimum projection data:

- external node identifier;
- display label and node type;
- observed status;
- x/y position when supplied;
- external link identifier;
- endpoint node identifiers and port labels when supplied;
- observation timestamp;
- optional bound inventory-device identifier.

Import does not infer a device from a name, console port, or address. Binding is
an explicit user action and cannot alter the registered device's credentials,
vendor, address, or SSH policy.

The frontend uses TanStack Query's existing polling behavior while the Topology
page is mounted. There is no scheduler or always-on polling service. On failure,
the last successful projection remains visible with a stale timestamp and
sanitized guidance; a failed poll never deletes prior nodes or links.

## 8. Change-Plan and Execution Model

### ChangePlan

A `ChangePlan` is the immutable intended change after Preview. For the pilot it
contains:

- plan and device identifiers;
- change type `interface_description`;
- one interface identifier selected from current observed inventory;
- desired bounded single-line description, or an explicit clear operation;
- pre-change snapshot identifier and content hash;
- encrypted rendered apply and assisted-rollback payloads;
- sanitized diff and risk summary;
- renderer/policy version;
- creation and expiry timestamps.

The interface is selected from current inventory instead of accepting arbitrary
CLI input. The first renderer permits only a bounded printable single-line
description with no control characters or line separators. It emits only:

```text
interface <observed-interface-name>
description <validated-text>
```

or:

```text
interface <observed-interface-name>
no description
```

There is no raw-command field in the API.

### ChangeExecution

Execution state is stored separately from the immutable plan:

- pending confirmation;
- applying;
- succeeded;
- failed;
- partial or unknown;
- rollback ready;
- rolled back.

Only one execution may own a device write lock. The lock uses a bounded lease
and idempotent release so API/worker cancellation cannot leave an unbounded
lock. A plan expiry or stale snapshot prevents lock acquisition and device
access.

### Maintenance Code

The operator opens a maintenance window for one ready plan. The backend creates
a random one-time code, displays it once, and stores only a keyed hash plus the
plan, device, local actor, expiry, and consumed state in Redis. The default and
fixed pilot lifetime is 15 minutes.

Apply submits the exact stored device name, code, and plan identifier. The code
is atomically consumed before the device write. A mismatch, replay, expiry, or
different device/plan fails without decrypting credentials or opening SSH.

Audit records may contain the maintenance-window identifier and sanitized
result, but never the code or hash.

## 9. Preview and Apply Data Flow

### Preview

1. Authenticate the local session and validate same-origin state-changing
   request protections.
2. Load one registered Cisco device and its pinned host key.
3. Validate the selected observed interface and description intent.
4. Run a bounded connection check and collect a fresh immutable running-config
   snapshot.
5. Derive the current interface description.
6. Render apply and assisted-rollback commands with the Cisco driver.
7. Validate that the renderer produced only the pilot command grammar.
8. Store the immutable plan and return a sanitized diff, risk, safety level,
   target summary, and the warning that startup-config will not be saved.

### Apply

1. Validate the exact device-name confirmation.
2. Atomically consume the Maintenance Code.
3. Acquire the per-device write lock.
4. Re-read the required state and compare it with the preview snapshot/hash.
5. Abort as stale if relevant state changed.
6. Decrypt credentials and open one pinned-host-key SSH session.
7. Enter configuration privilege explicitly and send the rendered command list.
8. Stop immediately on a failed or indeterminate response.
9. Read the resulting interface state/config through the structured read path.
10. Mark success only when the exact desired description is observed.
11. Release transport and lock through idempotent cleanup.

No step saves startup-config.

### Assisted rollback

A failure never starts rollback automatically. If the prior state is known, the
application creates a new rollback Preview from the original snapshot and the
currently observed state. Rollback requires a fresh device-name confirmation,
fresh Maintenance Code, lock, stale-state check, apply, and post-check.

## 10. Failure and Recovery Behavior

The structured-write path fails closed on:

- missing, unknown, or changed SSH host key;
- non-Cisco or unavailable capability;
- failed connection, authentication, or privilege acquisition;
- invalid interface or description;
- expired plan or Maintenance Code;
- reused or mismatched code;
- device lock conflict;
- preview/apply state drift;
- renderer output outside the allowlisted grammar;
- transport timeout/disconnect;
- rejected or indeterminate configuration response;
- failed or indeterminate post-check.

If a command may have applied partially, the execution status is `partial` or
`unknown`, never success. The system stops sending configuration, attempts only
the bounded read required to establish observed state when the connection is
stable, and presents recovery guidance. It does not hide uncertainty behind an
automatic rollback claim.

Provider failures use stable sanitized categories: URL rejected, route
unavailable, TLS trust required, certificate changed, authentication failed,
provider unavailable, rate limited, unsupported version/schema, or malformed
response. The last-good topology is retained and marked stale.

## 11. UI Requirements

Phase 1–2 closure covers user-visible states that block operation:

- loading, empty, disconnected, stale, failed, and retry guidance;
- responsive inventory, inspector, terminal, and topology layouts;
- keyboard navigation, focus restoration, accessible labels, and alert roles;
- explicit distinction between observed, inferred, manual-unverified, and
  external-provider topology;
- explicit virtual versus physical evidence labels.

The Phase 3 pilot UI must show, before Apply:

- device and interface;
- current and intended description;
- snapshot timestamp/hash reference;
- exact rendered diff without credentials or unrelated configuration;
- Safety Level C and no-auto-rollback warning;
- running-config-only warning;
- typed device-name field;
- Maintenance Code field and expiry;
- lock/stale-plan state;
- post-check and Assisted Rollback result.

Non-retryable errors must not leave an active Apply control. Refreshing or
recreating a plan is an explicit action.

## 12. Privacy and Audit Boundary

The following never enter application logs, analytics, telemetry, audit
payloads, backend error responses, or Git fixtures:

- device and provider credentials;
- Maintenance Codes or hashes;
- SSH private/session material;
- provider cookies;
- raw provider responses or exceptions;
- raw terminal commands/output;
- unsanitized running configuration;
- full encrypted change payloads.

Safe audit metadata is allowlisted and may include the local actor, device or
provider profile identifier, change type, plan/execution identifier, policy
version, timestamps, failure phase, sanitized result code, safety level, and
whether assisted rollback became available.

Lab validation records remain metadata-only. Virtual and physical outcomes are
separate and may not contain addresses, hostnames, serial numbers, credentials,
commands, output, configuration, screenshots, raw errors, provider cookies, or
session content.

## 13. Verification Strategy

### Routine automated verification

Routine tests remain network-free and use sanitized fixtures/fakes:

- Phase 1–2 conformance and user-flow regressions;
- Cisco interface-description renderer golden cases;
- clear description, invalid interface, control/newline, length, and stale
  inventory cases;
- immutable plan and snapshot behavior;
- expired, reused, wrong-device, and wrong-plan Maintenance Codes;
- lock conflict, lease expiry, cancellation, and idempotent cleanup;
- stale preview, partial apply, disconnect, timeout, and post-check failure;
- Assisted Rollback preview and fresh-confirmation requirements;
- first-contact host-key enrollment and changed-key rejection;
- provider URL/redirect/resolution/TLS/certificate boundaries;
- EVE-NG and GNS3 version, project, node, and link contract fixtures;
- malformed, oversized, and unexpected provider payloads;
- page-mounted polling cleanup and last-good stale behavior;
- manual binding without inventory mutation;
- secret/log/error/audit exclusion tests;
- frontend confirmation, disabled, focus, responsive, and accessibility states.

Automated test discovery never enables lab markers or opens network sockets.

### Authorized virtual and physical validation

Read-only acceptance retains the existing explicit lab opt-in and exact target.
Structured-write validation adds a second explicit opt-in and cannot be enabled
by the ordinary lab flag alone.

Before any write, the operator must confirm:

- exact authorized target and test window;
- pinned and independently checked SSH host key;
- working console/OOB path and named recovery owner;
- immutable pre-change snapshot;
- dedicated test interface and original description;
- no startup-config save;
- reviewed Preview, diff, risk, typed device name, and Maintenance Code.

The validation sequence is virtual Cisco first, then the authorized physical
Cisco device. It tests apply, post-check, Assisted Rollback, and restoration of
the original running description. It stops on any unexpected prompt, privilege,
drift, output, disconnect, or device behavior.

The physical one-device run does not claim physical CDP/LLDP topology support.
That claim remains pending until an authorized multi-device physical topology is
available.

## 14. Exit Gates

### Phase 1–2 readiness exit

- every final-plan Phase 1–2 requirement has a conformance row;
- all P0/P1 implementation gaps are closed or documented as an external
  hardware limitation;
- backend and frontend checks pass;
- current-main physical single-device acceptance passes for its declared scope;
- virtual multi-node acceptance passes for its declared scope;
- evidence records are sanitized and capability claims remain conservative.

### Local-lab provider exit

- encrypted EVE-NG and GNS3 profiles pass fake contract tests;
- same-host and management-LAN connectivity guidance is validated;
- GET-only import, normalization, manual binding, polling cleanup, and stale
  state pass automated tests;
- no emulator mutation endpoint exists in backend or frontend code;
- authorized virtual-lab validation passes for at least one supported provider,
  while the other remains explicitly unverified if unavailable.

### Phase 3 pilot exit

- only interface-description structured writes are declared;
- Preview, snapshot, diff/risk, typed name, one-time code, lock, stale check,
  apply, post-check, and Assisted Rollback work end to end;
- no startup-config save or automatic rollback path exists;
- automated verification passes;
- authorized virtual write validation passes before physical write validation;
- capability status remains lab-unverified until the exact dated evidence is
  recorded.

## 15. Out of Scope

- EVE-NG/GNS3 start, stop, suspend, reload, create, update, or delete operations;
- emulator project orchestration, console proxying, packet capture, or fault
  injection;
- automatic device creation or name/console-port matching;
- always-on provider polling or a new scheduler;
- Nornir, NAPALM, or another new network dependency;
- interface admin-state, VLAN, trunk, SVI, static-route, DNS, NTP, or SNMP
  configuration before pilot acceptance;
- startup-config save;
- automatic rollback or claims of guaranteed recovery;
- AI-generated changes or write tools;
- bulk reads/writes;
- cosmetic UI redesign.

## 16. Primary References

- [Scrapli documentation](https://github.com/carlmontanari/scrapli)
- [GNS3 API documentation](https://gns3-server.readthedocs.io/)
- [GNS3 architecture](https://docs.gns3.com/docs/using-gns3/design/architecture)
- [EVE-NG API documentation](https://www.eve-ng.net/index.php/how-to-eve-ng-api/)

EVE-NG documents that some calls evolve with the product. The adapter therefore
uses explicit version/capability probes, allowlisted read endpoints, bounded
schemas, and fixture evidence instead of assuming every edition/version returns
the same payload.
