from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from ipaddress import ip_address
from time import monotonic

from app.core.errors import DriverCommandRejectedError
from app.drivers.base import (
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
)
from app.drivers.generic_readonly import translate_transport_error
from app.drivers.ssh_errors import ConnectionPhase
from app.models import SafetyLevel, Vendor

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
                }
            ),
            safety_level=SafetyLevel.READ_ONLY,
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
