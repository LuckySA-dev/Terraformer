from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.core.errors import (
    DriverAuthenticationError,
    DriverTimeoutError,
    UnsupportedCapabilityError,
)
from app.drivers import (
    CiscoIOSXEDriver,
    ConnectionParameters,
    DriverCapability,
)
from app.drivers.cisco_iosxe import parse_show_interfaces, parse_show_version
from app.drivers.transport import ScrapliGenericTransport, ScrapliTransport
from tests.fakes import FakeTransportFactory


def parameters() -> ConnectionParameters:
    return ConnectionParameters(
        host="192.0.2.10",
        port=22,
        username="fixture-user",
        password="fixture-password",
        connect_timeout_seconds=7,
        command_timeout_seconds=41,
    )


def test_cisco_parsers_use_sanitized_golden_fixtures(sanitized_outputs: dict[str, str]) -> None:
    facts = parse_show_version(sanitized_outputs["show version"])
    interfaces = parse_show_interfaces(sanitized_outputs["show interfaces"])

    assert facts.hostname == "edge-rtr-01"
    assert facts.model == "C8000V"
    assert facts.serial_number == "9ABCDEF0123"
    assert facts.os_version == "17.09.04a"
    assert len(interfaces) == 3
    assert interfaces[0].name == "GigabitEthernet1"
    assert interfaces[0].admin_up is True
    assert interfaces[0].oper_up is True
    assert interfaces[0].ipv4_addresses == ("192.0.2.10/24",)
    assert interfaces[1].admin_up is False


def test_cisco_driver_is_read_only_and_closes_connections(
    sanitized_outputs: dict[str, str],
) -> None:
    factory = FakeTransportFactory(sanitized_outputs)
    driver = CiscoIOSXEDriver(factory)

    assert driver.capabilities.supports(DriverCapability.RUNNING_CONFIG)
    assert not driver.capabilities.supports(DriverCapability.APPLY)
    assert driver.get_facts(parameters()).hostname == "edge-rtr-01"
    assert driver.get_running_config(parameters()).startswith("version 17.9")
    assert all(transport.closed for transport in factory.transports)
    with pytest.raises(UnsupportedCapabilityError):
        driver.apply_configuration(parameters(), ["interface GigabitEthernet1"])


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (type("AuthenticationFailed", (Exception,), {})(), DriverAuthenticationError),
        (type("TransportTimeout", (Exception,), {})(), DriverTimeoutError),
    ],
)
def test_transport_errors_are_typed(error: Exception, expected: type[Exception]) -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}, open_error=error))
    with pytest.raises(expected):
        driver.test_connection(parameters())


def test_connection_and_command_timeouts_are_wired_independently(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeScrapli:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "scrapli", SimpleNamespace(Scrapli=FakeScrapli))
    ScrapliTransport(parameters(), strict_host_key=True)

    assert captured["timeout_socket"] == 7
    assert captured["timeout_transport"] == 7
    assert captured["timeout_ops"] == 41
    assert captured["auth_strict_key"] is True
    assert captured["platform"] == "cisco_iosxe"


def test_generic_transport_is_authenticated_but_vendor_neutral(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeGenericDriver:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    driver_module = SimpleNamespace(GenericDriver=FakeGenericDriver)
    monkeypatch.setitem(sys.modules, "scrapli.driver", driver_module)
    ScrapliGenericTransport(parameters(), strict_host_key=True)

    assert "platform" not in captured
    assert captured["auth_username"] == "fixture-user"
    assert captured["timeout_socket"] == 7
    assert captured["timeout_ops"] == 41
    assert captured["auth_strict_key"] is True


def test_malformed_cli_output_degrades_to_unknown_fields() -> None:
    facts = parse_show_version("unexpected output")
    assert facts.hostname is None
    assert facts.vendor == "Cisco"
    assert parse_show_interfaces("unexpected output") == []
