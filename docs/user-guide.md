# Phase 0–2 user guide

This guide covers local startup, first-run administration, topology,
diagnostics, and Direct Mode terminal access. Automated implementation is
complete, but real-device capabilities remain lab-unverified; check
`IMPLEMENTATION_STATUS.md` before relying on a screen or endpoint.

## 1. Start and check health

From the repository root, run one bootstrap command:

```powershell
.\deploy\start.ps1
```

or:

```bash
bash deploy/start.sh
```

The command preserves existing secrets, runs database migrations, and waits for
the stack. Browse to <http://127.0.0.1:8080>. If startup fails, inspect service
state and sanitized logs:

```powershell
docker compose -f deploy/compose.yml ps
docker compose -f deploy/compose.yml logs api worker migrate
```

Do not paste logs into a ticket until they have been reviewed for device data.

## 2. Complete first-run setup

Create the single local admin by choosing a strong master password. The admin
password is hashed; it is not `.secrets/master.key`, the database password, or a
device credential. Store it in your password manager.

The application is local-only by default. Do not change the bind address during
setup. LAN exposure is a separate security decision described in
`safety-model.md`.

## 3. Add one lab device

Only use a lab or explicitly approved management target.

1. Create a credential profile for a least-privilege read account.
2. Enter one exact management IP, SSH port, and Cisco IOS/IOS-XE vendor choice.
3. Run the connection test before saving.
4. Confirm the returned platform identity matches the physical target.
5. Approve the manual-add result, then request facts, interfaces, observed
   CDP/LLDP neighbors, and a running configuration snapshot.

The snapshot is observed device state. It must be immutable and must not be
presented as desired configuration. Abort on a platform mismatch, unexpected
privilege prompt, or parser warning.

## 3a. Prepare a device with Manual USB Console

Manual USB Console (USB Direct Mode) is available before registration for
operator-controlled console access. It is not read-only: anything typed or
pasted can modify, restart, or erase the attached hardware. It bypasses
Terraformer's structured validation, snapshots, locks, audit, and rollback.

Use Chrome or Edge on the same machine as the USB adapter. Open Terraformer
through HTTPS or localhost; the document must receive
`Permissions-Policy: serial=(self)`. Then:

1. Open **Inventory** and select **Open USB Console**.
2. Select the baud rate and line ending (`CR`, `LF`, or `CRLF`), and optionally
   enable local echo. Defaults are 9600 baud, 8 data bits, 1 stop bit, no parity,
   no flow control, `CR`, and local echo off.
3. Read the warning and acknowledge for this session that you are authorized to
   access the attached hardware and understand that commands can change it.
4. Select **Open USB Direct Mode**, then choose the intended adapter in the
   browser permission chooser. Verify it physically; Terraformer does not
   discover, identify, or remember adapters.
5. Type commands deliberately. A paste containing more than one logical line is
   held in memory and shows only its line count; confirm **Send** or cancel it.
6. Select **Disconnect** when finished. Navigation, adapter removal, or an I/O
   failure also starts cleanup. A later open is a fresh session and requires a
   new acknowledgement and adapter selection, with settings restored to the
   defaults.
7. After you have prepared the device outside Terraformer's automation,
   register it and test SSH separately using the normal inventory flow.

No adapter choice, settings, commands, output, raw errors, or terminal history is
persisted or sent to the backend, analytics, telemetry, or error reporting.
There is no automatic reconnect, command generation, starter configuration,
bootstrap workflow, vendor template, recording, or automatic command execution.

## 4. Discover candidates safely

Select **Discover**, enter one exact IPv4 network containing no more than 64
addresses, and start the bounded SSH-port probe. The worker uses fixed safe
defaults and stores only open-port candidates. It does not authenticate or add a
device. Review one candidate, select its driver and credential profile, then pass
the normal explicit connection test before approval.

Never enter a network without operator authorization. Discovery does not follow
CDP/LLDP neighbors and does not prove that an open port belongs to a network
device.

## 5. Inspect read-only state

The device inspector may show sanitized facts, interface operational state,
CDP/LLDP neighbor observations, snapshot metadata, and an event timeline.
“Observed” means read from a device; it does not guarantee freshness or create a
verified topology link. Refresh deliberately and avoid polling fragile equipment
repeatedly.

Open **Topology** to project registered devices and saved neighbor observations
onto a read-only canvas. Solid nodes are inventory records; dashed nodes are
observed evidence only. Dragged positions persist in this browser. Manual links
are browser-local and always labelled `UNVERIFIED`; they never create inventory
or cause device access. Choose manual, 30-second, or 60-second view refresh;
these refresh saved API data, not device state.

Open **Diagnostics** in a Cisco device inspector to request one fixed routing,
ARP, or MAC table read, or a bounded ping/traceroute to one exact IPv4 address.
The worker uses the registered device and encrypted credential profile; raw
commands, CIDR, hostnames, loopback, link-local, multicast, unspecified, and
reserved targets are rejected. Results are
sanitized, limited to 64 KiB, and may be downloaded locally. A timeout or
rejected command fails the job and does not trigger another command automatically.

Open **Terminal** only when an unrestricted interactive SSH session is required.
Read and accept the Direct Mode warning before every new session. Commands run
exactly as typed: there is no parser, approval plan, rollback guarantee, or
recording. The UI and API allow at most three sessions, idle input closes after
15 minutes, and each session has a 2 MiB output limit. Never paste secrets into
the terminal, and leave configuration mode unless a separately approved change
authorizes it.

For an end-of-support Cisco SSH implementation, select the device's explicit
compatibility mode before the required fresh connection test. `modern` is the
default; the two legacy modes are per-device exceptions and never automatic
fallbacks. Legacy modes do not change host-key verification. The server can
disable legacy SSH, Group1, or the terminal entirely; a disabled mode fails
closed. Device SSH terminal and USB Console are both manual Direct Mode and can
change hardware. **Automated verification passed; hardware validation pending.**

Check that events contain status and timing but no credential, enable secret, or
raw configuration. Report a possible leak privately and rotate the source
credential.

## Unavailable in this phase

- configuration render, preview, apply, post-check, and rollback;
- automatic CDP/LLDP traversal or verified manual-link persistence;
- Juniper NETCONF support;
- bulk operations and monitoring; and
- model-provider or local-model features.

Every structured driver capability therefore has Safety Level D for writes.
Direct Mode is the explicit exception: terminal input can alter a device and is
the operator's responsibility after the warning gate.

## Stop and retain data

```powershell
docker compose -f deploy/compose.yml down
```

Named volumes and `.secrets` remain. Never delete or replace `master.key` during
an upgrade. A destructive volume reset and secret deletion are separate,
intentional recovery operations described in the root README.
