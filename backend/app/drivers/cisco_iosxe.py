from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic

from app.drivers.base import (
    ConnectionParameters,
    ConnectionTestResult,
    DeviceDriver,
    DeviceFacts,
    DriverCapability,
    DriverCapabilitySet,
    InterfaceFacts,
    NetworkTransport,
    TransportFactory,
)
from app.drivers.generic_readonly import translate_transport_error
from app.models import SafetyLevel, Vendor

_INTERFACE_HEADER = re.compile(
    r"^(?P<name>\S+) is (?P<admin>administratively down|up|down), "
    r"line protocol is (?P<oper>up|down)",
    re.MULTILINE,
)
_MAC_ADDRESS = re.compile(r"address is ([0-9a-fA-F.:-]+)")
_IP_ADDRESS = re.compile(r"Internet address is (\S+)")
_SPEED = re.compile(r"\bBW\s+(\d+)\s+Kbit", re.IGNORECASE)


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
                    DriverCapability.RUNNING_CONFIG,
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

    def get_running_config(self, parameters: ConnectionParameters) -> str:
        output = self._command(parameters, "show running-config")
        if not output.strip():
            raise ValueError("The device returned an empty running configuration")
        return output.replace("\r\n", "\n")

    def _command(self, parameters: ConnectionParameters, command: str) -> str:
        with self._session(parameters) as transport:
            try:
                return transport.send_command(command)
            except Exception as exc:
                raise translate_transport_error(exc) from exc

    @contextmanager
    def _session(self, parameters: ConnectionParameters) -> Iterator[NetworkTransport]:
        transport = self._transport_factory(parameters)
        try:
            transport.open()
            yield transport
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            translated = translate_transport_error(exc)
            if isinstance(exc, type(translated)):
                raise
            raise translated from exc
        finally:
            try:
                transport.close()
            except Exception:  # noqa: S110 - close is best-effort and must not mask the operation
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
