# Phase 0–2 partial user guide

This guide covers local startup, first-run administration, and the read-only
Cisco IOS/IOS-XE slice. The implementation is intentionally incomplete; check
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

Check that events contain status and timing but no credential, enable secret, or
raw configuration. Report a possible leak privately and rotate the source
credential.

## Unavailable in this phase

- configuration render, preview, apply, post-check, and rollback;
- terminal and arbitrary show-command execution;
- automatic CDP/LLDP traversal and topology canvas;
- ping, traceroute, routing, ARP, and MAC diagnostics;
- Juniper NETCONF support;
- bulk operations and monitoring; and
- model-provider or local-model features.

Every device therefore has Safety Level D for writes. No UI or API control in
this phase should be able to alter a device.

## Stop and retain data

```powershell
docker compose -f deploy/compose.yml down
```

Named volumes and `.secrets` remain. Never delete or replace `master.key` during
an upgrade. A destructive volume reset and secret deletion are separate,
intentional recovery operations described in the root README.
