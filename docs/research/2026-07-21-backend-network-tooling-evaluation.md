# Backend network-tooling evaluation

Date: 2026-07-21
Scope: phases 0–1 of the [final plan](../network-automation-final-plan.md), with phase 2
discovery considered only where it explains the reported connection failure. No hardware or
network target was contacted.

## Decision

Keep the current split:

- **Scrapli** remains the structured Cisco IOS/IOS-XE CLI transport.
- **AsyncSSH** remains exclusive to the manual Web SSH terminal.
- Install Debian `openssh-client` in the backend **runtime** image. Do not add Netmiko or NAPALM
  to fix this failure.
- Keep discovery on Python sockets. Multiple ports may be probed, but an open TCP port is only an
  informational endpoint; it is not evidence that the service is SSH or that credentials work.

This is the smallest change which fixes the identified packaging mismatch without replacing the
tested driver boundary.

## Repository facts

- [`backend/pyproject.toml`](../../backend/pyproject.toml) pins `scrapli==2025.1.30` and
  `asyncssh==2.23.1`; Netmiko and NAPALM are absent.
- Local inspection of that exact locked Scrapli version reports `system` as the default
  for both `IOSXEDriver` and `GenericDriver`. Current upstream examples describe a newer
  transport API, so they are not an upgrade instruction for this fix.
- [`ScrapliTransport`](../../backend/app/drivers/transport.py) constructs the synchronous Scrapli
  IOS-XE driver without selecting a transport, so Scrapli's default `system` transport is used.
  Scrapli documents `transport="system"` as the default and exposes separate async drivers
  ([official IOS-XE driver reference](https://carlmontanari.github.io/scrapli/reference/driver/core/cisco_iosxe/async_driver/)).
- Scrapli's system transport starts an `ssh` process; its official source raises
  `ScrapliValueError` when no `ssh` executable exists on `PATH`
  ([official `PtyProcess` reference](https://carlmontanari.github.io/scrapli/reference/transport/plugins/system/ptyprocess/)).
  At evaluation time, the baseline [`backend/Dockerfile`](../../backend/Dockerfile) did not install
  an SSH client in either stage, so the image did not satisfy the selected transport's runtime
  requirement. The implementation now declares `openssh-client` in the runtime stage; Docker was
  unavailable in this session, so the rebuilt image itself was not executed.
- Structured reads already sit behind the small injected `NetworkTransport` protocol and fake
  transport ([base](../../backend/app/drivers/base.py),
  [fakes](../../backend/tests/fakes.py)). This gives deterministic fixture tests without any
  library-specific mocking.
- The manual terminal is intentionally separate and already uses AsyncSSH
  ([terminal route](../../backend/app/api/terminal.py)).
- Discovery currently performs bounded TCP connection attempts with `socket.create_connection`
  ([discovery service](../../backend/app/services/discovery.py)). A successful attempt proves only
  that the endpoint accepted TCP.

## Tool comparison

| Tool | Primary-source facts | Fit and recommendation |
|---|---|---|
| **Scrapli 2025.1.30** | Network-device CLI drivers include prompt/privilege handling and sync/async forms. Base installation has no Python dependencies; Paramiko, ssh2, AsyncSSH, TextFSM, and Genie are optional extras ([installation](https://carlmontanari.github.io/scrapli/user_guide/installation/)). The system transport shells out to OpenSSH and maps strict-key settings to `StrictHostKeyChecking` and a known-hosts file ([system transport](https://carlmontanari.github.io/scrapli/reference/transport/plugins/system/transport/)). It publishes authentication, connection, timeout, command, and transport exception classes ([exceptions](https://carlmontanari.github.io/scrapli/reference/exceptions/)). | **Keep.** It already matches the synchronous RQ/device-service flow, Cisco prompt handling, bounded timeouts, and existing fake transport. Install the missing OS dependency. |
| **Netmiko** | A synchronous multi-vendor library built to abstract network CLI state over Paramiko ([official repository](https://github.com/ktbyers/netmiko)). It has explicit authentication, connection, read, write, and timeout exception types ([exceptions](https://ktbyers.github.io/netmiko/docs/netmiko/exceptions.html)) and SSH device-type detection which executes platform probes ([SSHDetect](https://ktbyers.github.io/netmiko/docs/netmiko/ssh_autodetect.html)). Unknown host keys are accepted unless `ssh_strict` is enabled and host-key sources are configured ([API](https://ktbyers.github.io/netmiko/docs/netmiko/index.html)). | **Do not add now.** It replaces rather than complements Scrapli for this slice, adds Paramiko and a second prompt/transport model, remains synchronous, and does not remove the repository's capability and safety layer. SSHDetect also sends platform probes, so it must not replace passive discovery. |
| **NAPALM** | Provides a common multi-vendor API ([overview](https://napalm.readthedocs.io/en/latest/)). Its IOS driver uses Netmiko, not a native structured IOS API. IOS supports facts, interfaces, LLDP, config, ARP/MAC, ping, and traceroute getters, but not every getter ([support matrix](https://napalm.readthedocs.io/en/latest/support/)). Its IOS configuration features have device prerequisites and some operations can temporarily change device configuration ([IOS caveats](https://napalm.readthedocs.io/en/latest/support/ios.html)). It includes a fixture-driven mock driver ([mock driver](https://napalm.readthedocs.io/en/latest/tutorials/mock_driver.html)). | **Do not add in phases 0–1.** It would duplicate `DeviceDriver`, pull in Netmiko, expose write-capable APIs outside the current scope, and still leave gaps requiring custom commands/parsers. Evaluate one read-only adapter only after a second vendor creates measurable normalization duplication. |
| **AsyncSSH** | A native asyncio SSH implementation with OpenSSH-style known-hosts support and typed `PermissionDenied`, `HostKeyNotVerifiable`, key-exchange, and connection errors ([API](https://asyncssh.readthedocs.io/en/latest/api.html)). | **Keep for the manual terminal only.** It is appropriate for PTY/WebSocket concurrency but does not provide network-device prompt, privilege, paging, or command-failure semantics. Moving structured reads to it would recreate Scrapli and force async changes through synchronous services and RQ jobs. |
| **TextFSM + ntc-templates through Scrapli** | Scrapli can parse a response with TextFSM/ntc-templates, but its documented contract returns an empty list when template lookup or parsing fails ([response API](https://carlmontanari.github.io/scrapli/reference/response/)). | **Pilot later, do not add now.** It may replace brittle regex for commands with strong fixture coverage, but empty output must fail closed rather than silently become valid empty inventory. Add it only command by command after sanitized IOS/IOS-XE fixtures prove better coverage. |

## Required backend corrections

1. Install `openssh-client` only in the runtime image and smoke-test `ssh -V`.
2. Pass `transport="system"` explicitly in both Scrapli adapters.
3. Replace exception-name substring classification with published Scrapli exception types. Keep raw
   exception text out of responses and logs, and treat a missing runtime executable as service
   misconfiguration rather than device failure.
4. Replace the worker's traceback logging for sanitized `AppError` failures with error code/type
   metadata, and prevent Scrapli's own logger namespace from propagating raw OpenSSH messages to
   the application root logger. Otherwise either source can persist transport details even though
   the API response and job record are sanitized. Raise a fresh sanitized exception without a
   chained cause at the RQ boundary so RQ's stored `exc_info` cannot retain the original message.
5. Complete strict host-key operation with a read-only known-hosts mount/path before claiming strict
   verification in persistent or LAN-accessible deployments. Never auto-accept a changed key.
6. Keep multi-port discovery bounded and protocol-aware. Use one absolute read deadline so a
   slow-drip endpoint cannot extend the configured timeout. FTP and Telnet endpoints must not be sent
   to the SSH driver or made approvable as SSH devices.

## Verification gates

- Container build proves `ssh -V`; API and worker use the same rebuilt image.
- Fake-transport tests cover authentication, timeout, connection, missing executable/configuration,
  host-key rejection, cleanup, and raw-exception non-disclosure.
- Discovery tests cover multiple ports, deduplication, bounds, closed ports, and the rule that an
  open non-SSH port cannot be approved as an SSH device.
- Routine verification remains network-free. Real Cisco validation stays separately authorized and
  lab-unverified until recorded under the existing guide.

## Recommendation boundary

Facts above come from repository inspection and linked first-party documentation. The decisions to
retain Scrapli, avoid Netmiko/NAPALM now, and defer parser extras are recommendations based on the
current 1–50-device, maximum-10-connection, read-only phase boundary. A new library becomes justified
only when lab evidence or a second-vendor slice demonstrates a concrete gap and the change deletes
more local code than it adds.
