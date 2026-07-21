from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliModuleNotFound,
    ScrapliTimeout,
    ScrapliTransportPluginError,
    ScrapliValueError,
)

from app.core.errors import (
    ConfigurationError,
    DriverAuthenticationError,
    DriverCommandRejectedError,
    DriverConnectionError,
    DriverTimeoutError,
    UnsupportedCapabilityError,
)
from app.drivers import (
    CiscoIOSXEDriver,
    ConnectionParameters,
    DiagnosticAction,
    DriverCapability,
    GenericReadOnlyDriver,
)
from app.drivers.cisco_iosxe import (
    parse_cdp_neighbors,
    parse_lldp_neighbors,
    parse_show_interfaces,
    parse_show_version,
)
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
    cdp_neighbors = parse_cdp_neighbors(sanitized_outputs["show cdp neighbors detail"])
    lldp_neighbors = parse_lldp_neighbors(sanitized_outputs["show lldp neighbors detail"])

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
    assert cdp_neighbors[0].protocol == "cdp"
    assert cdp_neighbors[0].remote_device_name == "dist-sw-01.example.test"
    assert cdp_neighbors[0].management_address == "198.51.100.2"
    assert lldp_neighbors[0].protocol == "lldp"
    assert lldp_neighbors[0].local_interface == "GigabitEthernet2"
    assert lldp_neighbors[0].remote_interface == "GigabitEthernet1/0/48"


def test_cisco_driver_is_read_only_and_closes_connections(
    sanitized_outputs: dict[str, str],
) -> None:
    factory = FakeTransportFactory(sanitized_outputs)
    driver = CiscoIOSXEDriver(factory)

    assert driver.capabilities.supports(DriverCapability.RUNNING_CONFIG)
    assert driver.capabilities.supports(DriverCapability.NEIGHBORS)
    assert not driver.capabilities.supports(DriverCapability.APPLY)
    assert driver.get_facts(parameters()).hostname == "edge-rtr-01"
    assert len(driver.get_neighbors(parameters())) == 2
    assert driver.get_running_config(parameters()).startswith("version 17.9")
    assert all(transport.closed for transport in factory.transports)
    with pytest.raises(UnsupportedCapabilityError):
        driver.apply_configuration(parameters(), ["interface GigabitEthernet1"])


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ScrapliTimeout("raw-timeout-marker"), DriverTimeoutError),
        (
            ScrapliAuthenticationFailed("Permission denied raw-auth-marker"),
            DriverAuthenticationError,
        ),
        (
            ScrapliAuthenticationFailed("Timed out connecting raw-timeout-marker"),
            DriverTimeoutError,
        ),
        (
            ScrapliAuthenticationFailed("Host key verification failed raw-key-marker"),
            DriverConnectionError,
        ),
        (
            ScrapliAuthenticationFailed("No matching key exchange raw-kex-marker"),
            DriverConnectionError,
        ),
        (
            ScrapliValueError("ssh executable not found raw-runtime-marker"),
            ConfigurationError,
        ),
        (ScrapliModuleNotFound("raw-module-marker"), ConfigurationError),
        (ScrapliTransportPluginError("raw-plugin-marker"), ConfigurationError),
        (RuntimeError("raw-unknown-marker"), DriverConnectionError),
    ],
)
def test_transport_errors_are_typed_and_sanitized(
    error: Exception,
    expected: type[Exception],
) -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}, open_error=error))
    with pytest.raises(expected) as captured:
        driver.test_connection(parameters())

    assert "raw-" not in str(captured.value)


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
    assert captured["transport"] == "system"


def test_structured_system_transports_append_narrow_legacy_ssh_compatibility(
    monkeypatch,
) -> None:
    cisco_args: dict[str, object] = {}
    generic_args: dict[str, object] = {}

    class FakeScrapli:
        def __init__(self, **kwargs) -> None:
            cisco_args.update(kwargs)

    class FakeGenericDriver:
        def __init__(self, **kwargs) -> None:
            generic_args.update(kwargs)

    monkeypatch.setitem(sys.modules, "scrapli", SimpleNamespace(Scrapli=FakeScrapli))
    monkeypatch.setitem(
        sys.modules,
        "scrapli.driver",
        SimpleNamespace(GenericDriver=FakeGenericDriver),
    )

    ScrapliTransport(parameters(), strict_host_key=True)
    ScrapliGenericTransport(parameters(), strict_host_key=True)

    expected_open_cmd = [
        "-o",
        "KexAlgorithms=+diffie-hellman-group14-sha1",
        "-o",
        "HostKeyAlgorithms=+ssh-rsa",
        "-o",
        "Ciphers=+aes256-cbc",
    ]
    assert cisco_args["transport_options"] == {"open_cmd": expected_open_cmd}
    assert generic_args["transport_options"] == {"open_cmd": expected_open_cmd}
    assert "diffie-hellman-group1-sha1" not in " ".join(expected_open_cmd)
    assert "3des" not in " ".join(expected_open_cmd)


def test_scrapli_command_rejection_is_typed(monkeypatch) -> None:
    class FailedResponse:
        failed = True
        result = "sanitized fixture failure"

    class FakeScrapli:
        def __init__(self, **_kwargs) -> None:
            pass

        def send_command(self, _command: str) -> FailedResponse:
            return FailedResponse()

    monkeypatch.setitem(sys.modules, "scrapli", SimpleNamespace(Scrapli=FakeScrapli))
    transport = ScrapliTransport(parameters(), strict_host_key=True)

    with pytest.raises(DriverCommandRejectedError):
        transport.send_command("show version")


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
    assert captured["transport"] == "system"


def test_malformed_cli_output_degrades_to_unknown_fields() -> None:
    facts = parse_show_version("unexpected output")
    assert facts.hostname is None
    assert facts.vendor == "Cisco"
    assert parse_show_interfaces("unexpected output") == []
    assert parse_cdp_neighbors("unexpected output") == []
    assert parse_lldp_neighbors("unexpected output") == []


def test_read_operations_translate_command_timeout(
    sanitized_outputs: dict[str, str],
) -> None:
    error = ScrapliTimeout("raw-command-timeout-marker")
    driver = CiscoIOSXEDriver(FakeTransportFactory(sanitized_outputs, command_error=error))

    with pytest.raises(DriverTimeoutError):
        driver.get_neighbors(parameters())
    with pytest.raises(DriverTimeoutError):
        driver.run_diagnostic(parameters(), DiagnosticAction.ROUTING_TABLE)


def test_neighbor_collection_deduplicates_and_uses_lldp_chassis_fallback(
    sanitized_outputs: dict[str, str],
) -> None:
    outputs = dict(sanitized_outputs)
    outputs["show cdp neighbors detail"] *= 2
    outputs["show lldp neighbors detail"] = outputs["show lldp neighbors detail"].replace(
        "System Name: access-sw-01.example.test\n", ""
    )

    neighbors = CiscoIOSXEDriver(FakeTransportFactory(outputs)).get_neighbors(parameters())

    assert len(neighbors) == 2
    assert neighbors[1].remote_device_name == "0011.2233.4455"


def test_observation_batch_uses_one_session_and_tolerates_disabled_neighbors(
    sanitized_outputs: dict[str, str],
) -> None:
    factory = FakeTransportFactory(
        sanitized_outputs,
        command_errors={
            "show cdp neighbors detail": DriverCommandRejectedError(),
            "show lldp neighbors detail": DriverCommandRejectedError(),
        },
    )

    observations = CiscoIOSXEDriver(factory).collect_observations(parameters())

    assert observations.facts.hostname == "edge-rtr-01"
    assert len(observations.interfaces) == 3
    assert observations.neighbors == ()
    assert len(factory.transports) == 1
    assert factory.transports[0].closed is True


def test_required_command_rejection_keeps_typed_error(
    sanitized_outputs: dict[str, str],
) -> None:
    driver = CiscoIOSXEDriver(
        FakeTransportFactory(
            sanitized_outputs,
            command_errors={"show version": DriverCommandRejectedError()},
        )
    )

    with pytest.raises(DriverCommandRejectedError):
        driver.collect_observations(parameters())


def test_generic_neighbor_collection_fails_closed() -> None:
    driver = GenericReadOnlyDriver(FakeTransportFactory({}))

    assert not driver.capabilities.supports(DriverCapability.NEIGHBORS)
    with pytest.raises(UnsupportedCapabilityError):
        driver.get_neighbors(parameters())


@pytest.mark.parametrize(
    ("action", "command"),
    [
        (DiagnosticAction.ROUTING_TABLE, "show ip route"),
        (DiagnosticAction.ARP_TABLE, "show ip arp"),
        (DiagnosticAction.MAC_TABLE, "show mac address-table"),
    ],
)
def test_cisco_diagnostics_use_fixed_read_only_commands(
    action: DiagnosticAction,
    command: str,
) -> None:
    factory = FakeTransportFactory({command: "sanitized fixture output"})
    driver = CiscoIOSXEDriver(factory)

    assert driver.run_diagnostic(parameters(), action) == "sanitized fixture output"
    assert factory.transports[0].sent_commands == [command]
    assert factory.transports[0].closed is True


def test_generic_diagnostics_fail_closed() -> None:
    driver = GenericReadOnlyDriver(FakeTransportFactory({}))

    with pytest.raises(UnsupportedCapabilityError):
        driver.run_diagnostic(parameters(), DiagnosticAction.ROUTING_TABLE)


@pytest.mark.parametrize(
    ("action", "target", "command"),
    [
        (DiagnosticAction.PING, "198.51.100.10", "ping 198.51.100.10 repeat 3 timeout 1"),
        (
            DiagnosticAction.TRACEROUTE,
            "198.51.100.10",
            "traceroute 198.51.100.10 numeric timeout 1 probe 1",
        ),
    ],
)
def test_cisco_target_diagnostics_accept_only_canonical_ip(
    action: DiagnosticAction,
    target: str,
    command: str,
) -> None:
    factory = FakeTransportFactory({command: "sanitized fixture output"})
    driver = CiscoIOSXEDriver(factory)

    assert driver.run_diagnostic(parameters(), action, target) == "sanitized fixture output"
    assert factory.transports[0].sent_commands == [command]

    with pytest.raises(ValueError):
        driver.run_diagnostic(parameters(), action, f"{target};reload")
