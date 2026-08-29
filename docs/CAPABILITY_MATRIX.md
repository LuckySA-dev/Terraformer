# Capability matrix

Last updated: 2026-08-29
Scope: phases 0–3, plus read-only Batfish analysis

## Status definitions

- **Implemented, lab unverified** — code and automated fixture/unit coverage
  exist, but the exact platform has not been recorded in a real-lab result.
- **Lab verified** — sanitized automated evidence and a dated real-lab result
  exist for the recorded vendor, model, OS version, and transport.
- **Not Implemented** — no supported product path. It must fail closed.
- **Not Applicable** — the platform cannot provide the capability by design.

“Implemented” is not the same as “Supported.” Only a dated lab evidence record
can promote a capability to **Lab verified**.

## Structured read capabilities

| Capability | Cisco IOS/IOS-XE | Juniper Junos | Fortinet FortiOS | Generic/unknown |
|---|---|---|---|---|
| Explicit SSH connection test | Implemented, lab unverified | Not Implemented | Implemented, lab unverified | Implemented, lab unverified |
| Exact-device SSH host-key pinning | Implemented, lab unverified | Not Implemented | Implemented, lab unverified | Implemented, lab unverified |
| Platform identity/facts | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| Interface inventory/state | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| Running-config snapshot | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| Manual-add persistence | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| Sanitized event timeline | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| CDP/LLDP neighbors | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| Routing table | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| ARP/MAC tables | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |
| Bounded multi-port IPv4 SSH discovery | Implemented, lab unverified | Not Implemented | Implemented, lab unverified | Implemented, lab unverified |
| Ping/traceroute action | Implemented, lab unverified | Not Implemented | Not Implemented | Not Implemented |

The generic and Fortinet FortiOS drivers authenticate SSH only (connection tests and Direct Mode terminals); facts, interfaces, configuration, and structured diagnostics remain unsupported. Cisco and Fortinet read entries are deliberately lab-unverified. Before
release, link each to passing tests and record real-device acceptance below.
Discovery is vendor-neutral passive SSH identification only; it does not
authenticate, identify a platform, follow neighbors, or add inventory
automatically. Only endpoints whose received identification begins with
`SSH-` are approvable; other open TCP endpoints are informational only.
Only one discovery job may be queued or running at a time. Adding a candidate
still requires explicit approval and a successful authenticated connection test;
the resulting device and audit linkage are committed together.
The shared backend runtime includes the OpenSSH client required by the explicit
Scrapli system transport; this packaging evidence does not replace authorized
real-device validation, so SSH capabilities remain lab-unverified.
Every registered SSH path requires one exact device pin. First contact collects
only the public host key, returns algorithm and fingerprint to the UI, and does
not authenticate or run a command. Unknown, expired, mismatched, or changed
trust fails closed and requires explicit re-inspection; global SSH trust and
automatic legacy fallback are not used.
Both Scrapli adapters apply the same request-scoped password-only OpenSSH policy.
Synthetic catalog and unit tests cover connection timeout/refusal/loss, name
resolution, host-key unknown/changed, negotiation, authentication, PTY, and
terminal I/O mappings. This does not establish that pinned Scrapli emits every
distinct message: its system transport may collapse host-key conditions into an
indeterminate verification failure, which uses the conservative host-key-phase
fallback. PTY and terminal I/O entries are catalog behavior only; integration
with the real AsyncSSH terminal path belongs to Task 5. Hardware validation is
still pending, so none of this evidence promotes a vendor capability to Lab
verified.
The topology canvas is a UI projection, not a new device capability. It can show
any registered device, but current observed links come only from lab-unverified
Cisco CDP/LLDP records. Dashed observed nodes never become inventory implicitly.
Cisco routing, ARP, and MAC reads use three fixed driver mappings. The structured
diagnostics API accepts no raw commands or alternate targets. Results are sanitized and capped at 64 KiB;
implementation and fixture evidence do not promote them to Lab verified.
Cisco ping/traceroute accepts one validated exact IPv4 target and renders one
bounded vendor command; hostnames, CIDR, special-use targets, and command text
fail validation.

## Read-only analysis capabilities

Analysis derives conclusions from stored configuration. Results are labelled
`INFERRED` and are only as complete as the configuration set supplied. It is not
a device capability: no device is contacted, and "lab" below means validation
against a real Batfish container, not real network hardware.

| Capability | Cisco IOS/IOS-XE | Juniper Junos | Fortinet FortiOS | Generic/unknown |
|---|---|---|---|---|
| Configuration parse and hygiene findings | Implemented, real-Batfish verified | Not Implemented | Not Implemented | Not Implemented |
| Path check (logical traceroute) | Implemented, real-Batfish verified | Not Implemented | Not Implemented | Not Implemented |
| Filter/ACL check | Implemented, real-Batfish verified | Not Implemented | Not Implemented | Not Implemented |
| Topology drift against observed neighbours | Implemented, fake-backend unit tested only | Not Implemented | Not Implemented | Not Implemented |

Analysis requires the optional Compose profile and `ANALYSIS_ENABLED`. Both are
off by default. The enforced device bound (`ANALYSIS_MAX_DEVICES`, default 200)
is not a supported capacity; see `docs/IMPLEMENTATION_STATUS.md`.
Configuration parse and interface-property extraction are covered by an opt-in
automated test (`backend/tests/analysis/test_real_batfish.py`) that runs this
application's own sanitized Cisco fixture through a real Batfish container.
Path check and filter/ACL check were validated once by hand against the same
container — including a genuine ACL `DENY` result with the correct matched
line — but do not yet have a committed automated regression test against real
Batfish. Topology drift's own logic is unit tested only against a fake backend;
the interface-property data it consumes is the same data already verified
against a real container above.

## Direct access paths

Direct access is recorded separately because it is operator-controlled manual
access, not a structured driver read or write capability. Manual Direct Mode is
outside structured Safety Levels A–D; its warning gate does not prevent commands
from writing to or changing hardware.

| Access path | Status | Vendor scope | Safety and evidence boundary |
|---|---|---|---|
| Web SSH terminal Direct Mode | **Implemented; lab verified for Cisco Catalyst 2960/2960X/3650 and ISR 2911 under Cisco Legacy mode, otherwise lab unverified** | Registered devices with an available SSH transport | **Automated verification passed; physical lab verified for the four device categories above (2026-08-11), hardware validation pending for all other vendors/models/modes.** Can write or otherwise change hardware; separate from drivers and structured Safety Levels A–D. Authenticated, same-origin, warning-gated, and resource-bounded; commands/output are never audit payloads. |
| Manual USB Console / USB Direct Mode | **Implemented, lab unverified** | Vendor-neutral manual serial access | **Automated verification passed; hardware validation pending.** Can write, modify, restart, or erase hardware; bypasses backend and structured safety controls. Automated fake-stream, privacy, lifecycle, serving-policy, type, lint, and build checks passed on 2026-07-20; no vendor/device support claim. |

Cisco Legacy SSH terminal is **Physical lab verified** for Catalyst 2960,
2960X, 3650, and ISR 2911 (see the record below). Fortinet legacy/very-old SSH
terminal, Cisco very-old SSH terminal, and topology claims remain **Implemented,
lab unverified** until separately authorized hardware validation is recorded.
Very Old SSH mode (`very_old_ssh`) requires all three compatibility kill
switches (`SSH_LEGACY_ENABLED`, `SSH_GROUP1_ENABLED`, `SSH_VERY_OLD_ENABLED`)
to be enabled simultaneously.

### Direct Mode hardware evidence

USB Direct Mode has no authorized hardware validation recorded; that portion of
this table must remain empty until an explicitly approved real-adapter session
is completed. Entries may contain only the metadata allowed by
`lab-test-guide.md`; never serial-session content.

| Date | Approver | Browser/version | Adapter/transport type | Device category | Application commit | Requested compatibility mode | Non-command validation-step descriptions | Pass/fail outcome |
|---|---|---|---|---|---|---|---|---|
| 2026-08-11 | LuckySA (Owner) | Chrome 151.0.0.0 | SSH | Cisco Catalyst 2960, 2960X, 3650; Cisco ISR 2911 | 48b776d | Cisco Legacy | Connection test, structured facts/interface/neighbor read, and Direct Mode terminal open, connect, and disconnect lifecycle completed via the UI for each device category | Pass |

## Structured write capabilities

Structured writes are optional (`STRUCTURED_WRITES_ENABLED`, off by default) and
cover eleven Cisco IOS/IOS-XE change types: interface description, interface
admin state, VLAN name, interface access VLAN, interface trunk allowed VLANs,
static route, adding and removing one network statement in a RIP/EIGRP/OSPF
process, the RIP version, one BGP neighbour, and hostname. Saving running-config to startup-config is a seventh write, but it is
an action rather than a change type: it is an exec command, it alters no
running state, and it has no inverse, so it does not go through the Change Plan
pipeline. Every other capability and platform remains **Not Implemented**,
and the application must not expose an API, worker job, driver fallback, or structured UI control that can execute them. Manual Direct Mode
remains the explicit path outside this table and outside Safety Levels A–D.

| Capability | Cisco IOS/IOS-XE | Juniper Junos | Fortinet FortiOS | Generic/unknown |
|---|---|---|---|---|
| Render interface description/admin state | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render VLAN name (creates the VLAN) | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render interface access VLAN | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render trunk allowed VLANs | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render hostname | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Save running-config to startup-config | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render SVI/IP address | **Not Implemented** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render static route | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render RIP/EIGRP/OSPF network statement (add and remove) | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render RIP version | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Render BGP neighbour | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Validate rendered commands | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Candidate/compare | **Not Implemented** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Pre-change snapshot pipeline | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Apply configuration | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Post-change checks | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Confirmed commit | **Not Implemented** | **Not Implemented** | **Not Implemented** | **Not Implemented** |
| Rollback/assisted recovery | **Implemented, lab unverified** | **Not Implemented** | **Not Implemented** | **Not Implemented** |

Current structured-write safety classification: all eleven Cisco IOS/IOS-XE
change types are **Level C, lab unverified** ("Best effort; never
'auto-rollback'"). Several carry a caveat worth stating here and not only in
code. A trunk
allowed-VLAN change **replaces** the list rather than adding to it, so every
VLAN omitted stops crossing that link; it is classified HIGH risk whenever the
port's link is up. Saving running-config is verified only by the device's own
acknowledgement, not by an independent read-back of startup-config, which is
weaker than a Change Plan's post-check. A static route is read from the running
configuration rather than the routing table, because a route whose next hop is
currently unreachable is absent from `show ip route` but still configured;
repointing a prefix withdraws the old line in the same change, since two
`ip route` lines for one prefix are alternative paths rather than an edit. A
default route and a repointed prefix are both classified HIGH.

A RIP/EIGRP/OSPF change adds or withdraws exactly one `network` statement in
one process. When the process is not running an add starts it, which is why the
rollback for that case removes the whole process rather than the statement, and
why it is classified HIGH; so is a statement whose wildcard covers every
address, because it enables the protocol on the management interface too. A
removal is always HIGH -- whatever reached that network through this device
stops reaching it -- and is refused unless the process already carries the
statement, since withdrawing an absent one would produce a rollback that adds
configuration rather than undoing any.

The RIP version is its own change type and is always HIGH: v1 and v2 do not
interoperate, so changing it drops every adjacency the process had, and setting
it on a process that does not exist starts RIP.

A BGP change configures one peer. IOS runs a single BGP process per device, so
a local AS that does not match the one already configured is refused here
rather than sent to be refused there. Re-pointing an existing peer withdraws it
first, because one neighbour cannot hold two remote-as values. It is always
HIGH: a session can move or withdraw a large amount of reachability as soon as
it comes up.

Every routing post-check confirms the configuration is present, not that the
protocol converged -- which is the only thing any change in this pipeline has
ever claimed.

Every other platform and capability remains **Level D — Read-only**. The opt-in real-lab test
(`backend/tests/lab/test_structured_writes_lab.py`) exists but has not been run
against a real device — see the verification record in
`docs/IMPLEMENTATION_STATUS.md`.

## Real-lab evidence log

No lab verification has been recorded yet.
Phase 1 release/exit remains blocked. The fixture-backed Phase 2 neighbor slice
also remains lab-unverified until an authorized read-only Cisco run supplies
sanitized evidence for this table.

| Date | Vendor/model | OS version | Capability set | Fixture/test reference | Result | Operator |
|---|---|---|---|---|---|---|
| — | — | — | — | — | Not run | — |

When adding an entry, never include an address, hostname, serial number,
credential, full configuration, or other identifying lab data. Keep the raw
evidence outside Git and attach only sanitized hashes/summaries.
