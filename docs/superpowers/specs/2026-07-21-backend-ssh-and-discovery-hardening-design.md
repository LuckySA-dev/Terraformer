# Backend SSH and Discovery Hardening Design

Date: 2026-07-21
Status: Approved

## Problem

The backend image uses Scrapli's default `system` transport but does not contain the
OpenSSH `ssh` executable. Candidate and saved-device connection tests therefore fail
before reaching the device and the broad transport-error mapping reports the local
runtime problem as a device-facing 502.

Discovery is a separate issue. It currently probes one TCP port for every address in
an explicitly authorized IPv4 CIDR. A successful TCP connection is recorded as an SSH
candidate even though no SSH protocol identification was observed.

## Goals

- Make the existing Scrapli system transport runnable in the shared API/worker image.
- Keep structured Cisco reads behind the existing `NetworkTransport` and
  `DeviceDriver` boundaries.
- Return sanitized, useful error categories without returning, logging, or persisting
  raw browser, OpenSSH, Scrapli, credential, command, or device output.
- Let an operator scan a small list of TCP ports inside the existing authorized CIDR.
- Allow approval only for endpoints which supplied an SSH identification line.
- Keep all routine verification network-free and all capabilities lab-unverified until
  an explicitly authorized hardware test is recorded.

## Non-goals

- No Netmiko, NAPALM, Nornir, Nmap, FTP, or Telnet client is added.
- No automatic transport fallback, platform detection, login attempt, command execution,
  topology expansion, or device creation is added to discovery.
- No parser replacement, generated configuration, bootstrap workflow, or structured
  device-write path is added.
- `docs/network-automation-final-plan.md` remains unchanged.

## Slice A: SSH runtime hardening

The runtime stage of `backend/Dockerfile` installs Debian `openssh-client` with
`--no-install-recommends` and removes apt metadata in the same layer. The builder stage
does not need it. API, worker, and migration services already share this runtime image.

`ScrapliTransport` and `ScrapliGenericTransport` explicitly pass
`transport="system"`. This makes the executable dependency visible instead of relying
on Scrapli's default.

`translate_transport_error()` keeps its existing public contract but maps installed
Scrapli exception types:

- existing `AppError` values pass through unchanged;
- `ScrapliTimeout` becomes `DriverTimeoutError`;
- `ScrapliAuthenticationFailed` becomes `DriverAuthenticationError` only for known
  credential-rejection signals; its known OpenSSH timeout signal becomes
  `DriverTimeoutError`; host-key, negotiation, address, and unknown signals become
  `DriverConnectionError` so the UI does not falsely blame the profile;
- `ScrapliValueError`, `ScrapliModuleNotFound`, and
  `ScrapliTransportPluginError` become the existing `ConfigurationError`;
- other exceptions fail closed to `DriverConnectionError`.

Only sanitized application error codes and default messages leave the backend. Raw
exception strings are inspected in memory only where Scrapli collapses multiple OpenSSH
failures into `ScrapliAuthenticationFailed`; they are never returned or recorded.
Background jobs log only the sanitized application error code and exception class, not
an exception traceback, so a chained Scrapli/OpenSSH cause cannot reach persistent logs.
Scrapli's own logger namespace also stops at its installed null handler rather than
propagating raw OpenSSH messages into the application's root logger.
The RQ callable raises a fresh sanitized exception `from None` after recording failure
state, so RQ's persisted failure traceback cannot retain the original exception chain.

## Slice B: bounded multi-port SSH-aware discovery

`DiscoveryRequest` changes from one `port` to `ports`, defaulting to `[22]`. It accepts
one to four unique ports in the inclusive range 1–65535. Duplicate input is normalized
while preserving order. Existing limits remain: exact IPv4 CIDR, at most 64 addresses,
concurrency 1–10, connection timeout no greater than five seconds, delay 10–1000 ms,
and the configured global connection limit. The maximum work is therefore 256 endpoint
probes per job.

The standard-library socket probe connects to each `address:port`, reads at most 512
bytes within one absolute per-endpoint deadline, and classifies the endpoint without
sending bytes:

- `ssh` when any received identification line starts with `SSH-`;
- `open_tcp` when TCP opened but no SSH identification was observed;
- closed/unreachable when the connection failed.

No banner content is retained. `DiscoveryResult.scanned_count` counts endpoint probes,
not unique addresses. SSH endpoints remain in `candidates`; non-SSH open endpoints are
returned separately as `open_endpoints`. `approve_candidate()` checks only
`candidates`, so an open FTP, Telnet, HTTP, or unknown service can never reach a device
driver from the discovery approval path.

The UI accepts a comma-separated list of at most four ports, displays the effective
endpoint bound, shows SSH candidates with the existing Review and approve action, and
shows `open_tcp` endpoints as informational, non-actionable results. Backend validation
remains authoritative. Passive identification can produce a safe false negative when a
non-standard server waits for client bytes; the operator can still use Manual Add and an
explicit connection test for that authorized endpoint.

## Verification

- A source regression test verifies the runtime package declaration; a container smoke
  check runs `ssh -V` when Docker is available.
- Unit tests verify explicit Scrapli transport selection, sanitized typed error mapping,
  multi-port normalization and bounds, SSH banner classification, closed endpoints,
  concurrency limiting, and the 256-probe ceiling.
- Integration tests verify job payload/result shape, rejection of open non-SSH endpoint
  approval, and explicit approval of an SSH candidate.
- Frontend tests verify submitted ports, scan bounds, actionable SSH candidates, and
  informational non-SSH endpoints.
- Ruff, Pyright, pytest, frontend verification, Compose configuration, and image smoke
  run before handoff. Lab tests remain skipped unless separately authorized.

## Tooling decision

Scrapli remains the structured Cisco CLI transport and AsyncSSH remains terminal-only.
Netmiko would duplicate the current transport model, while NAPALM's IOS driver brings
Netmiko and write-capable APIs without removing the repository's safety/capability
layer. TextFSM plus ntc-templates is a possible later parser pilot, command by command,
only after sanitized fixtures prove it deletes more parser code than it adds. Empty
template output must fail closed rather than silently mean empty inventory.

The installed and locked Scrapli version is `2025.01.30`; its local signatures default
the IOS-XE and generic drivers to `system`. Current upstream documentation describes a
newer transport API, so this slice does not upgrade Scrapli or copy examples from a
different release line.
