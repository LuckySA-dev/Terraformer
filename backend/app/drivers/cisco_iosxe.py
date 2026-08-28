from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from ipaddress import ip_address
from time import monotonic
from typing import cast

from app.changes.types import ChangeStepIntent, RenderedChange
from app.core.errors import DriverCommandRejectedError
from app.drivers.base import (
    ChangeContext,
    ConfigurableTransport,
    ConnectionParameters,
    ConnectionTestResult,
    DeviceDriver,
    DeviceFacts,
    DeviceObservations,
    DiagnosticAction,
    DriverCapability,
    DriverCapabilitySet,
    InterfaceFacts,
    NeighborFacts,
    NetworkTransport,
    TransportFactory,
    VlanFacts,
)
from app.drivers.generic_readonly import translate_transport_error
from app.drivers.ssh_errors import ConnectionPhase
from app.models import ChangeType, SafetyLevel, Vendor

_INTERFACE_HEADER = re.compile(
    r"^(?P<name>\S+) is (?P<admin>administratively down|up|down), "
    r"line protocol is (?P<oper>up|down)",
    re.MULTILINE,
)
_MAC_ADDRESS = re.compile(r"address is ([0-9a-fA-F.:-]+)")
_IP_ADDRESS = re.compile(r"Internet address is (\S+)")
_SPEED = re.compile(r"\bBW\s+(\d+)\s+Kbit", re.IGNORECASE)
_DIAGNOSTIC_COMMANDS = {
    DiagnosticAction.ROUTING_TABLE: "show ip route",
    DiagnosticAction.ARP_TABLE: "show ip arp",
    DiagnosticAction.MAC_TABLE: "show mac address-table",
}


class CiscoIOSXEDriver(DeviceDriver):
    vendor = Vendor.CISCO_IOSXE
    name = "cisco_iosxe"

    def __init__(self, transport_factory: TransportFactory) -> None:
        self._transport_factory = transport_factory
        self._capabilities = DriverCapabilitySet(
            supported=frozenset(
                {
                    DriverCapability.CONNECT,
                    DriverCapability.FACTS,
                    DriverCapability.INTERFACES,
                    DriverCapability.NEIGHBORS,
                    DriverCapability.RUNNING_CONFIG,
                    DriverCapability.ROUTING,
                    DriverCapability.ARP,
                    DriverCapability.MAC,
                    DriverCapability.PING,
                    DriverCapability.TRACEROUTE,
                    DriverCapability.RENDER,
                    DriverCapability.VALIDATE,
                    DriverCapability.APPLY,
                    DriverCapability.POST_CHECK,
                    DriverCapability.ROLLBACK,
                    DriverCapability.SAVE_CONFIG,
                }
            ),
            safety_level=SafetyLevel.BEST_EFFORT,
        )

    @property
    def capabilities(self) -> DriverCapabilitySet:
        return self._capabilities

    def test_connection(self, parameters: ConnectionParameters) -> ConnectionTestResult:
        started = monotonic()
        with self._session(parameters):
            pass
        return ConnectionTestResult(
            reachable=True,
            driver=self.name,
            message="SSH connection succeeded",
            latency_ms=max(0, int((monotonic() - started) * 1_000)),
        )

    def get_facts(self, parameters: ConnectionParameters) -> DeviceFacts:
        output = self._command(parameters, "show version")
        return parse_show_version(output)

    def get_interfaces(self, parameters: ConnectionParameters) -> list[InterfaceFacts]:
        output = self._command(parameters, "show interfaces")
        return parse_show_interfaces(output)

    def get_vlans(self, parameters: ConnectionParameters) -> list[VlanFacts]:
        # A router has no VLAN database and rejects the command. That is not
        # an error worth failing a preview over -- an empty table simply means
        # "no VLAN facts", and the VLAN change types are refused elsewhere.
        try:
            return parse_show_vlan_brief(self._command(parameters, "show vlan brief"))
        except DriverCommandRejectedError:
            return []

    def get_neighbors(self, parameters: ConnectionParameters) -> list[NeighborFacts]:
        with self._session(parameters) as transport:
            return self._read_neighbors(transport)

    def collect_observations(self, parameters: ConnectionParameters) -> DeviceObservations:
        with self._session(parameters) as transport:
            facts = parse_show_version(transport.send_command("show version"))
            interfaces = parse_show_interfaces(transport.send_command("show interfaces"))
            neighbors = self._read_neighbors(transport)
        return DeviceObservations(
            facts=facts,
            interfaces=tuple(interfaces),
            neighbors=tuple(neighbors),
        )

    def _read_neighbors(self, transport: NetworkTransport) -> list[NeighborFacts]:
        observations: list[NeighborFacts] = []
        for command, parser in (
            ("show cdp neighbors detail", parse_cdp_neighbors),
            ("show lldp neighbors detail", parse_lldp_neighbors),
        ):
            try:
                observations.extend(parser(transport.send_command(command)))
            except DriverCommandRejectedError:
                continue
        unique = {
            (
                item.protocol,
                item.local_interface,
                item.remote_device_name,
                item.remote_interface,
            ): item
            for item in observations
        }
        return list(unique.values())

    def get_running_config(self, parameters: ConnectionParameters) -> str:
        output = self._command(parameters, "show running-config")
        if not output.strip():
            raise ValueError("The device returned an empty running configuration")
        return output.replace("\r\n", "\n")

    _DESCRIPTION_MAX_LENGTH = 240
    _VLAN_NAME_MAX_LENGTH = 32
    _VLAN_ID_MIN = 1
    _VLAN_ID_MAX = 4094

    _HOSTNAME_MAX_LENGTH = 63
    _HOSTNAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")

    def render_change(self, step: ChangeStepIntent, context: ChangeContext) -> RenderedChange:
        if step.change_type is ChangeType.HOSTNAME:
            return self._render_hostname(step, context)
        if step.change_type is ChangeType.VLAN_NAME:
            return self._render_vlan_name(step, context)
        if step.change_type is ChangeType.INTERFACE_ACCESS_VLAN:
            return self._render_access_vlan(step, context)
        current = context.interface
        if current is None:
            self._unsupported(DriverCapability.RENDER)
        if step.change_type is ChangeType.INTERFACE_DESCRIPTION:
            inverse_value = current.description
            inverse = (
                (f"interface {step.target}", f"description {inverse_value}")
                if inverse_value
                else (f"interface {step.target}", "no description")
            )
            return RenderedChange(
                commands=(f"interface {step.target}", f"description {step.desired_value}"),
                inverse_commands=inverse,
            )
        if step.change_type is ChangeType.INTERFACE_ADMIN_STATE:
            desired_up = step.desired_value == "up"
            current_up = bool(current.admin_up)
            return RenderedChange(
                commands=(
                    f"interface {step.target}",
                    "no shutdown" if desired_up else "shutdown",
                ),
                inverse_commands=(
                    f"interface {step.target}",
                    "no shutdown" if current_up else "shutdown",
                ),
            )
        self._unsupported(DriverCapability.RENDER)

    def _render_hostname(self, step: ChangeStepIntent, context: ChangeContext) -> RenderedChange:
        previous = context.hostname
        # Without a readable current hostname there is no inverse to roll back
        # to, and a Level C change with no inverse is not one this pipeline is
        # allowed to stage.
        if not previous:
            self._unsupported(DriverCapability.RENDER)
        return RenderedChange(
            commands=(f"hostname {step.desired_value}",),
            inverse_commands=(f"hostname {previous}",),
        )

    def _render_vlan_name(self, step: ChangeStepIntent, context: ChangeContext) -> RenderedChange:
        vlan_id = int(step.target)
        existing = context.vlan(vlan_id)
        # Naming a VLAN that does not exist creates it, so the inverse of a
        # create is a delete -- but only when this change is what created it.
        # Renaming an existing VLAN must never roll back into deleting it.
        inverse: tuple[str, ...] = (
            (f"vlan {vlan_id}", f"name {existing.name}")
            if existing is not None
            else (f"no vlan {vlan_id}",)
        )
        return RenderedChange(
            commands=(f"vlan {vlan_id}", f"name {step.desired_value}"),
            inverse_commands=inverse,
        )

    def _render_access_vlan(self, step: ChangeStepIntent, context: ChangeContext) -> RenderedChange:
        previous = context.access_vlan_of(step.target)
        inverse: tuple[str, ...] = (
            (f"interface {step.target}", f"switchport access vlan {previous.vlan_id}")
            if previous is not None
            else (f"interface {step.target}", "no switchport access vlan")
        )
        return RenderedChange(
            # `switchport mode access` is included because assigning an access
            # VLAN on a port left in dynamic mode does not reliably take
            # effect -- the port has to actually be an access port first.
            commands=(
                f"interface {step.target}",
                "switchport mode access",
                f"switchport access vlan {int(step.desired_value)}",
            ),
            inverse_commands=inverse,
        )

    def validate_change(self, step: ChangeStepIntent, context: ChangeContext) -> list[str]:
        issues: list[str] = []
        if step.change_type is ChangeType.HOSTNAME:
            return self._validate_hostname(step)
        if step.change_type is ChangeType.VLAN_NAME:
            return self._validate_vlan_name(step)
        if step.change_type is ChangeType.INTERFACE_ACCESS_VLAN:
            return self._validate_access_vlan(step, context)
        if step.change_type is ChangeType.INTERFACE_DESCRIPTION:
            if len(step.desired_value) > self._DESCRIPTION_MAX_LENGTH:
                issues.append(
                    f"description must be {self._DESCRIPTION_MAX_LENGTH} characters or fewer"
                )
            # A description is interpolated into one config line, stored
            # newline-joined with the rest of the batch, and split back into
            # lines at apply time. Any control character therefore smuggles an
            # extra command into a batch the operator vetted at preview -- the
            # one input on this path that is free-form text, so the one that
            # has to be constrained to a single printable line.
            if not step.desired_value.isprintable():
                issues.append("description must be a single line of printable characters")
            elif not step.desired_value.strip():
                issues.append(
                    "description must not be empty; clear it with a separate change instead"
                )
        elif step.change_type is ChangeType.INTERFACE_ADMIN_STATE:
            if step.desired_value not in ("up", "down"):
                issues.append("admin state must be 'up' or 'down'")
        return issues

    def _validate_hostname(self, step: ChangeStepIntent) -> list[str]:
        issues: list[str] = []
        name = step.desired_value
        if len(name) > self._HOSTNAME_MAX_LENGTH:
            issues.append(f"hostname must be {self._HOSTNAME_MAX_LENGTH} characters or fewer")
        # Same reasoning as a description: this is interpolated into one config
        # line that is split back apart at apply time, so anything outside a
        # bare word could smuggle a second command into a vetted batch. IOS is
        # stricter than that anyway -- a hostname starts with a letter and
        # carries only letters, digits and hyphens.
        if not self._HOSTNAME_PATTERN.match(name):
            issues.append(
                "hostname must start with a letter and contain only letters, digits and hyphens"
            )
        return issues

    def _validate_vlan_name(self, step: ChangeStepIntent) -> list[str]:
        issues: list[str] = []
        issues.extend(self._vlan_id_issues(step.target, field="VLAN id"))
        name = step.desired_value
        if len(name) > self._VLAN_NAME_MAX_LENGTH:
            issues.append(f"VLAN name must be {self._VLAN_NAME_MAX_LENGTH} characters or fewer")
        # Same reasoning as an interface description: this is free-form text
        # interpolated into a config line that is later split back apart, so a
        # control character or a space would smuggle a second command into a
        # batch the operator already reviewed. IOS VLAN names are additionally
        # restricted to a word, which makes the rule stricter here.
        if not name.strip():
            issues.append("VLAN name must not be empty")
        elif not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
            issues.append("VLAN name may only contain letters, digits, hyphen and underscore")
        return issues

    def _validate_access_vlan(self, step: ChangeStepIntent, context: ChangeContext) -> list[str]:
        issues: list[str] = []
        issues.extend(self._vlan_id_issues(step.desired_value, field="access VLAN"))
        if issues:
            return issues
        # Assigning a port to a VLAN the switch does not have leaves the port
        # in an inactive VLAN and black-holes it. Refuse instead: create the
        # VLAN first, as its own reviewable change.
        if context.vlans and context.vlan(int(step.desired_value)) is None:
            issues.append(
                f"VLAN {step.desired_value} does not exist on this device; "
                "create it first with a VLAN name change"
            )
        return issues

    def _vlan_id_issues(self, raw: str, *, field: str) -> list[str]:
        try:
            vlan_id = int(raw)
        except ValueError:
            return [f"{field} must be a number"]
        if not self._VLAN_ID_MIN <= vlan_id <= self._VLAN_ID_MAX:
            return [f"{field} must be between {self._VLAN_ID_MIN} and {self._VLAN_ID_MAX}"]
        # 1002-1005 are reserved by IOS for legacy FDDI/Token Ring and cannot
        # be renamed or freely assigned.
        if 1002 <= vlan_id <= 1005:
            return [f"{field} {vlan_id} is reserved by IOS"]
        return []

    def apply_configuration(self, parameters: ConnectionParameters, commands: list[str]) -> None:
        self._config(parameters, commands)

    # IOS answers a successful save with "[OK]" and reports any failure with a
    # line starting "%". Both are checked: a save that silently did nothing is
    # the failure mode that matters, since the operator would otherwise
    # believe the configuration survives a reload.
    _SAVE_OK = "[OK]"

    def save_configuration(self, parameters: ConnectionParameters) -> str:
        # `write memory` is an exec command, not a configuration one, so it
        # cannot go through _config()'s `configure terminal` wrapper.
        output = self._command(parameters, "write memory")
        cleaned = output.replace("\r\n", "\n")
        if any(line.lstrip().startswith("%") for line in cleaned.splitlines()):
            raise ValueError("The device rejected the save command")
        if self._SAVE_OK not in cleaned:
            raise ValueError("The device did not confirm the save")
        return cleaned

    def rollback(self, parameters: ConnectionParameters, commands: list[str]) -> None:
        self._config(parameters, commands)

    def _config(self, parameters: ConnectionParameters, commands: Sequence[str]) -> None:
        with self._session(parameters) as transport:
            # _session()'s transport is typed as the shared NetworkTransport
            # (no send_config -- see ConfigurableTransport's docstring), but
            # this driver's own transport_factory always produces one that
            # supports it: this method is only reachable through apply_
            # configuration/rollback, gated by this driver's own APPLY/
            # ROLLBACK capability declaration, which only Cisco advertises.
            cast(ConfigurableTransport, transport).send_config(commands)

    def run_diagnostic(
        self,
        parameters: ConnectionParameters,
        action: DiagnosticAction,
        target: str | None = None,
    ) -> str:
        if action in _DIAGNOSTIC_COMMANDS:
            command = _DIAGNOSTIC_COMMANDS[action]
        elif target is None:
            raise ValueError("A diagnostic target is required")
        else:
            canonical_target = str(ip_address(target))
            command = (
                f"ping {canonical_target} repeat 3 timeout 1"
                if action == DiagnosticAction.PING
                else f"traceroute {canonical_target} numeric timeout 1 probe 1"
            )
        return self._command(parameters, command)

    def _command(self, parameters: ConnectionParameters, command: str) -> str:
        with self._session(parameters) as transport:
            return transport.send_command(command)

    @contextmanager
    def _session(self, parameters: ConnectionParameters) -> Iterator[NetworkTransport]:
        transport: NetworkTransport | None = None
        try:
            try:
                transport = self._transport_factory(parameters)
                transport.open()
            except Exception as exc:
                raise translate_transport_error(
                    exc,
                    phase=ConnectionPhase.TCP,
                ) from None
            try:
                yield transport
            except Exception as exc:
                translated = translate_transport_error(exc, phase=ConnectionPhase.TERMINAL_IO)
                raise translated from None
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:  # noqa: S110 - close must not mask the operation
                    pass


def parse_show_version(output: str) -> DeviceFacts:
    hostname_match = re.search(r"(?m)^(\S+) uptime is (.+)$", output)
    version_match = re.search(
        r"(?:Cisco IOS XE Software|Cisco IOS Software).*?Version\s+([^,\s]+)",
        output,
        re.IGNORECASE,
    )
    model_match = re.search(r"(?mi)^cisco\s+(\S+).*?processor", output)
    serial_match = re.search(r"(?mi)^Processor board ID\s+(\S+)", output)
    return DeviceFacts(
        hostname=hostname_match.group(1) if hostname_match else None,
        vendor="Cisco",
        model=model_match.group(1) if model_match else None,
        serial_number=serial_match.group(1) if serial_match else None,
        os_version=version_match.group(1) if version_match else None,
        uptime=hostname_match.group(2).strip() if hostname_match else None,
    )


def parse_show_interfaces(output: str) -> list[InterfaceFacts]:
    matches = list(_INTERFACE_HEADER.finditer(output))
    interfaces: list[InterfaceFacts] = []
    for index, match in enumerate(matches):
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(output)
        block = output[match.start() : block_end]
        description_match = re.search(r"(?m)^\s+Description:\s*(.+)$", block)
        mac_match = _MAC_ADDRESS.search(block)
        ip_matches = tuple(ip.group(1) for ip in _IP_ADDRESS.finditer(block))
        speed_match = _SPEED.search(block)
        interfaces.append(
            InterfaceFacts(
                name=match.group("name"),
                description=description_match.group(1).strip() if description_match else None,
                admin_up=match.group("admin") == "up",
                oper_up=match.group("oper") == "up",
                mac_address=mac_match.group(1).lower() if mac_match else None,
                ipv4_addresses=ip_matches,
                speed_mbps=(int(speed_match.group(1)) // 1_000) if speed_match else None,
            )
        )
    return interfaces


# "10   USERS    active    Gi1/0/1, Gi1/0/2"
_VLAN_ROW = re.compile(r"(?m)^(?P<id>\d{1,4})\s+(?P<name>\S+)\s+(?P<status>\S+)\s*(?P<ports>.*)$")


def parse_show_vlan_brief(output: str) -> list[VlanFacts]:
    """Parses `show vlan brief`, including its wrapped port continuation lines.

    A VLAN with more ports than fit the column continues on following lines
    that carry only ports. Dropping those would under-report membership,
    which is exactly what the access-VLAN inverse command depends on.
    """
    vlans: list[VlanFacts] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.lower().startswith("vlan "):
            continue
        match = _VLAN_ROW.match(line.rstrip())
        if match is None:
            # A continuation line: ports only, belonging to the VLAN above.
            if vlans and re.fullmatch(r"[A-Za-z0-9/,\.\s-]+", stripped):
                previous = vlans[-1]
                vlans[-1] = VlanFacts(
                    vlan_id=previous.vlan_id,
                    name=previous.name,
                    status=previous.status,
                    ports=previous.ports + _split_ports(stripped),
                )
            continue
        vlans.append(
            VlanFacts(
                vlan_id=int(match.group("id")),
                name=match.group("name"),
                status=match.group("status"),
                ports=_split_ports(match.group("ports")),
            )
        )
    return vlans


def _split_ports(raw: str) -> tuple[str, ...]:
    return tuple(port.strip() for port in raw.split(",") if port.strip())


def parse_cdp_neighbors(output: str) -> list[NeighborFacts]:
    neighbors: list[NeighborFacts] = []
    for block in re.split(r"(?m)^-+\s*$", output):
        device = re.search(r"(?mi)^Device ID:\s*(\S+)", block)
        local = re.search(r"(?mi)^Interface:\s*([^,]+)", block)
        remote = re.search(r"(?mi)Port ID \(outgoing port\):\s*(\S+)", block)
        if device is None or local is None or remote is None:
            continue
        address = re.search(r"(?mi)^\s*IP address:\s*(\S+)", block)
        platform = re.search(r"(?mi)^Platform:\s*([^,\r\n]+)", block)
        neighbors.append(
            NeighborFacts(
                protocol="cdp",
                local_interface=local.group(1).strip(),
                remote_device_name=device.group(1),
                remote_interface=remote.group(1),
                management_address=address.group(1) if address else None,
                platform=platform.group(1).strip() if platform else None,
            )
        )
    return neighbors


def parse_lldp_neighbors(output: str) -> list[NeighborFacts]:
    starts = list(re.finditer(r"(?mi)^Local Intf:\s*(.+)$", output))
    neighbors: list[NeighborFacts] = []
    for index, start in enumerate(starts):
        block_end = starts[index + 1].start() if index + 1 < len(starts) else len(output)
        block = output[start.start() : block_end]
        device = re.search(r"(?mi)^System Name:\s*(\S+)", block) or re.search(
            r"(?mi)^Chassis id:\s*(\S+)", block
        )
        remote = re.search(r"(?mi)^Port id:\s*(\S+)", block)
        if device is None or remote is None:
            continue
        address = re.search(r"(?mi)^\s*IP:\s*(\S+)", block)
        platform = re.search(r"(?mi)^System Description:\s*(.+)$", block)
        neighbors.append(
            NeighborFacts(
                protocol="lldp",
                local_interface=start.group(1).strip(),
                remote_device_name=device.group(1),
                remote_interface=remote.group(1),
                management_address=address.group(1) if address else None,
                platform=platform.group(1).strip() if platform else None,
            )
        )
    return neighbors
