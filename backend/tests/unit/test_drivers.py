from __future__ import annotations

import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest
from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliConnectionError,
    ScrapliModuleNotFound,
    ScrapliTimeout,
    ScrapliTransportPluginError,
    ScrapliValueError,
)

from app.changes.types import ChangeStepIntent
from app.core import errors as core_errors
from app.core.errors import (
    ConfigurationError,
    DriverAuthenticationError,
    DriverCommandRejectedError,
    DriverConnectionError,
    DriverHostKeyVerificationError,
    DriverSSHNegotiationError,
    DriverTerminalIOError,
    DriverTerminalPTYError,
    DriverTimeoutError,
    UnsupportedCapabilityError,
)
from app.drivers import (
    CiscoIOSXEDriver,
    ConnectionParameters,
    DiagnosticAction,
    DriverCapability,
    GenericReadOnlyDriver,
    InterfaceFacts,
)
from app.drivers.cisco_iosxe import (
    parse_cdp_neighbors,
    parse_lldp_neighbors,
    parse_show_interfaces,
    parse_show_version,
)
from app.drivers.ssh_errors import ConnectionPhase, translate_ssh_error
from app.drivers.transport import ScrapliGenericTransport, ScrapliTransport
from app.models import ChangeType, SSHCompatibility
from tests.fakes import FakeTransportFactory

# The fixed, sanitized guidance returned for every negotiation failure. Spelled
# out here rather than imported so a change to the user-facing text has to be
# made deliberately in both places.
_NEGOTIATION_ACTION = (
    "The device and this client share no usable SSH algorithm. Select a"
    " higher SSH compatibility mode for this device. Older Cisco switches"
    " and routers often also need a regenerated 2048-bit host key."
)


def parameters() -> ConnectionParameters:
    return ConnectionParameters(
        host="192.0.2.10",
        port=22,
        username="fixture-user",
        password="fixture-password",
        known_hosts="192.0.2.10 ssh-ed25519 AAAAfixture\n",
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
    assert driver.get_facts(parameters()).hostname == "edge-rtr-01"
    assert len(driver.get_neighbors(parameters())) == 2
    assert driver.get_running_config(parameters()).startswith("version 17.9")
    assert all(transport.closed for transport in factory.transports)


def test_cisco_driver_capability_set_now_includes_write_capabilities() -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    for capability in (
        DriverCapability.RENDER,
        DriverCapability.VALIDATE,
        DriverCapability.APPLY,
        DriverCapability.POST_CHECK,
        DriverCapability.ROLLBACK,
    ):
        assert driver.capabilities.supports(capability)
    assert not driver.capabilities.supports(DriverCapability.COMPARE)


def test_cisco_driver_renders_interface_description_change(
    sanitized_outputs: dict[str, str],
) -> None:
    factory = FakeTransportFactory({"show interfaces": sanitized_outputs["show interfaces"]})
    driver = CiscoIOSXEDriver(factory)
    current = driver.get_interfaces(parameters())
    target = next(iface for iface in current if iface.name == "GigabitEthernet1")

    step = ChangeStepIntent(
        change_type=ChangeType.INTERFACE_DESCRIPTION,
        target="GigabitEthernet1",
        desired_value="uplink-to-lab-core-2",
    )
    rendered = driver.render_change(step, target)

    assert rendered.commands == (
        "interface GigabitEthernet1",
        "description uplink-to-lab-core-2",
    )
    assert rendered.inverse_commands == (
        "interface GigabitEthernet1",
        f"description {target.description}",
    )


def test_cisco_driver_renders_interface_description_inverse_as_no_description_when_absent(
    sanitized_outputs: dict[str, str],
) -> None:
    factory = FakeTransportFactory({"show interfaces": sanitized_outputs["show interfaces"]})
    driver = CiscoIOSXEDriver(factory)
    current = driver.get_interfaces(parameters())
    target = next(iface for iface in current if iface.name == "GigabitEthernet2")
    assert target.description is None

    step = ChangeStepIntent(
        change_type=ChangeType.INTERFACE_DESCRIPTION,
        target="GigabitEthernet2",
        desired_value="new description",
    )
    rendered = driver.render_change(step, target)

    assert rendered.inverse_commands == ("interface GigabitEthernet2", "no description")


def test_cisco_driver_renders_admin_state_change_both_directions() -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    current_up = InterfaceFacts(
        name="GigabitEthernet1", description=None, admin_up=True, oper_up=True
    )

    down = driver.render_change(
        ChangeStepIntent(ChangeType.INTERFACE_ADMIN_STATE, "GigabitEthernet1", "down"),
        current_up,
    )
    assert down.commands == ("interface GigabitEthernet1", "shutdown")
    assert down.inverse_commands == ("interface GigabitEthernet1", "no shutdown")

    current_down = InterfaceFacts(
        name="GigabitEthernet1", description=None, admin_up=False, oper_up=False
    )
    up = driver.render_change(
        ChangeStepIntent(ChangeType.INTERFACE_ADMIN_STATE, "GigabitEthernet1", "up"),
        current_down,
    )
    assert up.commands == ("interface GigabitEthernet1", "no shutdown")
    assert up.inverse_commands == ("interface GigabitEthernet1", "shutdown")


def test_cisco_driver_validate_change_rejects_a_description_over_240_characters() -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    current = InterfaceFacts(name="GigabitEthernet1", description=None, admin_up=True, oper_up=True)
    step = ChangeStepIntent(ChangeType.INTERFACE_DESCRIPTION, "GigabitEthernet1", "x" * 241)

    issues = driver.validate_change(step, current)

    assert issues == ["description must be 240 characters or fewer"]


def test_cisco_driver_validate_change_accepts_a_valid_description() -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    current = InterfaceFacts(name="GigabitEthernet1", description=None, admin_up=True, oper_up=True)
    step = ChangeStepIntent(ChangeType.INTERFACE_DESCRIPTION, "GigabitEthernet1", "fine")

    assert driver.validate_change(step, current) == []


def test_cisco_driver_validate_change_rejects_a_description_carrying_extra_commands() -> None:
    """A newline in the description would become a second config command.

    render_change interpolates the value into one line, the plan stores the
    batch newline-joined, and apply splits it back into lines -- so an
    embedded newline smuggles an arbitrary command past the vetted change
    types the whole Level C pipeline is built on.
    """
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    current = InterfaceFacts(name="GigabitEthernet1", description=None, admin_up=True, oper_up=True)
    step = ChangeStepIntent(ChangeType.INTERFACE_DESCRIPTION, "GigabitEthernet1", "ok\nshutdown")

    assert driver.validate_change(step, current) == [
        "description must be a single line of printable characters"
    ]


def test_cisco_driver_validate_change_rejects_an_empty_description() -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    current = InterfaceFacts(name="GigabitEthernet1", description=None, admin_up=True, oper_up=True)
    step = ChangeStepIntent(ChangeType.INTERFACE_DESCRIPTION, "GigabitEthernet1", "   ")

    assert driver.validate_change(step, current) == [
        "description must not be empty; clear it with a separate change instead"
    ]


def test_cisco_driver_apply_configuration_sends_a_config_mode_batch() -> None:
    factory = FakeTransportFactory({})
    driver = CiscoIOSXEDriver(factory)

    driver.apply_configuration(
        parameters(), ["interface GigabitEthernet1", "description new-desc"]
    )

    assert factory.transports[0].sent_config_batches == [
        ["interface GigabitEthernet1", "description new-desc"]
    ]
    assert factory.transports[0].closed is True


def test_cisco_driver_apply_configuration_raises_typed_error_when_a_command_is_rejected() -> None:
    factory = FakeTransportFactory(
        {}, command_errors={"description new-desc": DriverCommandRejectedError()}
    )
    driver = CiscoIOSXEDriver(factory)

    with pytest.raises(DriverCommandRejectedError):
        driver.apply_configuration(
            parameters(), ["interface GigabitEthernet1", "description new-desc"]
        )
    assert factory.transports[0].closed is True


def test_cisco_driver_rollback_sends_the_inverse_commands() -> None:
    factory = FakeTransportFactory({})
    driver = CiscoIOSXEDriver(factory)

    driver.rollback(parameters(), ["interface GigabitEthernet1", "no shutdown"])

    assert factory.transports[0].sent_config_batches == [
        ["interface GigabitEthernet1", "no shutdown"]
    ]


def test_cisco_driver_closes_transport_when_open_fails() -> None:
    factory = FakeTransportFactory({}, open_error=RuntimeError("raw-open-marker"))
    driver = CiscoIOSXEDriver(factory)

    with pytest.raises(DriverConnectionError):
        driver.test_connection(parameters())

    assert factory.transports[0].closed is True


@pytest.mark.parametrize("driver_type", [CiscoIOSXEDriver, GenericReadOnlyDriver])
@pytest.mark.parametrize(
    ("factory_error", "expected_type", "expected_details"),
    [
        (
            ScrapliValueError(
                "raw-constructor-marker edge-rtr-01.example.test fixture-password "
                "peer-offered-ssh-rsa"
            ),
            ConfigurationError,
            {"phase": "tcp_connection", "retryable": False},
        ),
        (
            RuntimeError(
                "raw-constructor-marker edge-rtr-01.example.test fixture-password "
                "peer-offered-ssh-rsa"
            ),
            DriverConnectionError,
            {
                "phase": "tcp_connection",
                "retryable": True,
                "recommended_action": (
                    "Verify device reachability and that SSH is listening on the configured port."
                ),
            },
        ),
    ],
)
def test_transport_factory_failures_are_tcp_sanitized(
    driver_type,
    factory_error: Exception,
    expected_type: type[Exception],
    expected_details: dict[str, object],
) -> None:
    raw_values = (
        type(factory_error).__name__,
        "raw-constructor-marker",
        "edge-rtr-01.example.test",
        "fixture-password",
        "peer-offered-ssh-rsa",
    )
    factory = FakeTransportFactory({}, factory_error=factory_error)
    driver = driver_type(factory)

    with pytest.raises(expected_type) as captured:
        driver.test_connection(parameters())

    assert captured.value.details == expected_details
    assert captured.value.__suppress_context__ is True
    rendered = "".join(traceback.format_exception(captured.type, captured.value, captured.tb))
    assert all(raw not in rendered for raw in raw_values)
    assert factory.transports == []


@pytest.mark.parametrize("driver_type", [CiscoIOSXEDriver, GenericReadOnlyDriver])
def test_constructed_transport_is_closed_exactly_once_when_open_fails(driver_type) -> None:
    factory = FakeTransportFactory({}, open_error=RuntimeError("raw-open-marker"))
    driver = driver_type(factory)

    with pytest.raises(DriverConnectionError):
        driver.test_connection(parameters())

    assert factory.transports[0].close_calls == 1


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


def test_authentication_failure_has_only_fixed_safe_metadata() -> None:
    raw_values = (
        "raw-auth-marker",
        "edge-rtr-01.example.test",
        "fixture-password",
        "peer-offered-ssh-rsa",
        "ScrapliAuthenticationFailed",
    )
    driver = CiscoIOSXEDriver(
        FakeTransportFactory(
            {},
            open_error=ScrapliAuthenticationFailed(
                "Permission denied raw-auth-marker edge-rtr-01.example.test "
                "fixture-password peer-offered-ssh-rsa"
            ),
        )
    )

    with pytest.raises(DriverAuthenticationError) as captured:
        driver.test_connection(parameters())

    assert captured.value.details == {
        "phase": "authentication",
        "retryable": False,
        "recommended_action": ("Verify the selected credential profile and device login policy."),
    }
    rendered = "".join(traceback.format_exception(captured.type, captured.value, captured.tb))
    assert all(raw not in rendered for raw in raw_values)


def test_connection_and_command_timeouts_are_wired_independently(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeScrapli:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def close(self) -> None:
            pass

    monkeypatch.setitem(sys.modules, "scrapli", SimpleNamespace(Scrapli=FakeScrapli))
    transport = ScrapliTransport(parameters())

    assert captured["timeout_socket"] == 7
    assert captured["timeout_transport"] == 7
    assert captured["timeout_ops"] == 41
    assert captured["auth_strict_key"] is True
    assert captured["platform"] == "cisco_iosxe"
    assert captured["transport"] == "system"
    transport.close()


def test_scrapli_uses_only_device_pin_and_removes_temp_file(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeScrapli:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def open(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setitem(sys.modules, "scrapli", SimpleNamespace(Scrapli=FakeScrapli))
    transport = ScrapliTransport(parameters())
    transport.open()
    options = captured["transport_options"]["open_cmd"]  # type: ignore[index]
    path_option = next(str(item) for item in options if str(item).startswith("UserKnownHostsFile="))
    known_hosts_path = Path(path_option.partition("=")[2])

    assert known_hosts_path.read_text(encoding="utf-8") == (
        "192.0.2.10 ssh-ed25519 AAAAfixture\n"
    )
    assert "StrictHostKeyChecking=yes" in options
    assert "GlobalKnownHostsFile=none" in options
    transport.close()
    transport.close()
    assert not known_hosts_path.exists()


def test_scrapli_removes_device_pin_after_open_failure(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeScrapli:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def open(self) -> None:
            raise RuntimeError("raw-open-error")

        def close(self) -> None:
            pass

    monkeypatch.setitem(sys.modules, "scrapli", SimpleNamespace(Scrapli=FakeScrapli))
    transport = ScrapliTransport(parameters())
    options = captured["transport_options"]["open_cmd"]  # type: ignore[index]
    path_option = next(str(item) for item in options if str(item).startswith("UserKnownHostsFile="))
    known_hosts_path = Path(path_option.partition("=")[2])

    with pytest.raises(RuntimeError, match="raw-open-error"):
        transport.open()
    transport.close()
    assert not known_hosts_path.exists()


def test_scrapli_transports_force_password_only_authentication(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    class FakeConnection:
        def __init__(self, **kwargs) -> None:
            captured.append(kwargs)

        def close(self) -> None:
            pass

    monkeypatch.setitem(sys.modules, "scrapli", SimpleNamespace(Scrapli=FakeConnection))
    monkeypatch.setitem(
        sys.modules,
        "scrapli.driver",
        SimpleNamespace(GenericDriver=FakeConnection),
    )

    secret_parameters = ConnectionParameters(
        host="192.0.2.10",
        port=22,
        username="fixture-user",
        password="fixture-password",
        enable_password="fixture-enable-password",
        known_hosts="192.0.2.10 ssh-ed25519 AAAAfixture\n",
    )
    transports = [ScrapliTransport(secret_parameters), ScrapliGenericTransport(secret_parameters)]

    expected = [
        "-o",
        "IdentityAgent=none",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "PreferredAuthentications=password",
        "-o",
        "PasswordAuthentication=yes",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "HostbasedAuthentication=no",
        "-o",
        "GSSAPIAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=1",
    ]
    for constructor in captured:
        open_cmd = constructor["transport_options"]["open_cmd"]  # type: ignore[index]
        assert open_cmd[: len(expected)] == expected
        assert "StrictHostKeyChecking=yes" in open_cmd
        assert "GlobalKnownHostsFile=none" in open_cmd
        assert secret_parameters.password not in expected
        assert secret_parameters.enable_password not in expected
    for transport in transports:
        transport.close()


@pytest.mark.parametrize(
    ("mode", "algorithm_options"),
    [
        (SSHCompatibility.MODERN, ()),
        (
            SSHCompatibility.CISCO_LEGACY,
            (
                "KexAlgorithms=+diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1",
                "HostKeyAlgorithms=+ssh-rsa",
                "Ciphers=+aes256-cbc,aes192-cbc,aes128-cbc",
                "MACs=+hmac-sha1,hmac-sha1-96",
            ),
        ),
        (
            SSHCompatibility.CISCO_LEGACY_GROUP1,
            (
                "KexAlgorithms=+diffie-hellman-group14-sha1,"
                "diffie-hellman-group-exchange-sha1,diffie-hellman-group1-sha1",
                "HostKeyAlgorithms=+ssh-rsa",
                "Ciphers=+aes256-cbc,aes192-cbc,aes128-cbc",
                "MACs=+hmac-sha1,hmac-sha1-96",
            ),
        ),
        (
            SSHCompatibility.VERY_OLD_SSH,
            (
                "KexAlgorithms=+diffie-hellman-group14-sha1,"
                "diffie-hellman-group-exchange-sha1,diffie-hellman-group1-sha1",
                "HostKeyAlgorithms=+ssh-rsa,ssh-dss",
                "Ciphers=+aes256-cbc,aes192-cbc,aes128-cbc,3des-cbc",
                "MACs=+hmac-sha1,hmac-sha1-96,hmac-md5,hmac-md5-96",
            ),
        ),
    ],
)
def test_scrapli_transports_scope_exact_compatibility_options(
    monkeypatch,
    mode: SSHCompatibility,
    algorithm_options: tuple[str, ...],
) -> None:
    captured: list[dict[str, object]] = []

    class FakeConnection:
        def __init__(self, **kwargs) -> None:
            captured.append(kwargs)

        def close(self) -> None:
            pass

    monkeypatch.setitem(sys.modules, "scrapli", SimpleNamespace(Scrapli=FakeConnection))
    monkeypatch.setitem(
        sys.modules,
        "scrapli.driver",
        SimpleNamespace(GenericDriver=FakeConnection),
    )
    secret_parameters = ConnectionParameters(
        host="192.0.2.10",
        port=22,
        username="fixture-user",
        password="fixture-password",
        enable_password="fixture-enable-password",
        known_hosts="192.0.2.10 ssh-ed25519 AAAAfixture\n",
        ssh_compatibility=mode,
    )

    transports = [ScrapliTransport(secret_parameters), ScrapliGenericTransport(secret_parameters)]

    authentication_options = (
        "IdentityAgent=none",
        "IdentitiesOnly=yes",
        "PreferredAuthentications=password",
        "PasswordAuthentication=yes",
        "PubkeyAuthentication=no",
        "KbdInteractiveAuthentication=no",
        "HostbasedAuthentication=no",
        "GSSAPIAuthentication=no",
        "NumberOfPasswordPrompts=1",
    )
    expected = [
        item for option in (*authentication_options, *algorithm_options) for item in ("-o", option)
    ]
    for constructor in captured:
        open_cmd = constructor["transport_options"]["open_cmd"]  # type: ignore[index]
        assert open_cmd[: len(expected)] == expected
        assert "StrictHostKeyChecking=yes" in open_cmd
        assert "GlobalKnownHostsFile=none" in open_cmd
        assert secret_parameters.password not in open_cmd
    for transport in transports:
        transport.close()
        assert secret_parameters.enable_password not in open_cmd


@pytest.mark.parametrize(
    ("error", "phase", "expected_type", "expected_details"),
    [
        (
            ScrapliTimeout("raw-timeout-marker"),
            ConnectionPhase.TCP,
            DriverTimeoutError,
            {
                "phase": "tcp_connection",
                "retryable": True,
                "recommended_action": (
                    "Retry after verifying device reachability and network latency."
                ),
            },
        ),
        (
            ScrapliAuthenticationFailed("Permission denied raw-auth-marker"),
            ConnectionPhase.NEGOTIATION,
            DriverAuthenticationError,
            {
                "phase": "authentication",
                "retryable": False,
                "recommended_action": (
                    "Verify the selected credential profile and device login policy."
                ),
            },
        ),
        (
            ScrapliAuthenticationFailed("No matching key exchange raw-kex-marker"),
            ConnectionPhase.NEGOTIATION,
            DriverSSHNegotiationError,
            {
                "phase": "ssh_negotiation",
                "retryable": False,
                "recommended_action": _NEGOTIATION_ACTION,
            },
        ),
        (
            ScrapliAuthenticationFailed("Host key verification failed raw-host-marker"),
            ConnectionPhase.NEGOTIATION,
            DriverHostKeyVerificationError,
            {
                "phase": "host_key_verification",
                "retryable": False,
                "recommended_action": "Verify the saved SSH host key for this device.",
            },
        ),
        (
            ScrapliValueError("raw-configuration-marker"),
            ConnectionPhase.TCP,
            ConfigurationError,
            {"phase": "tcp_connection", "retryable": False},
        ),
        (
            RuntimeError("raw-pty-marker"),
            ConnectionPhase.PTY,
            DriverTerminalPTYError,
            {
                "phase": "pty_creation",
                "retryable": False,
                "recommended_action": "Verify the device permits PTY and shell creation.",
            },
        ),
    ],
)
def test_ssh_error_catalog_is_typed_and_contains_only_fixed_metadata(
    error: Exception,
    phase: ConnectionPhase,
    expected_type: type[Exception],
    expected_details: dict[str, object],
) -> None:
    translated = translate_ssh_error(error, phase=phase)

    assert type(translated) is expected_type
    assert translated.details == expected_details
    assert "raw-" not in str(translated)
    assert "raw-" not in repr(translated.details)


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_type"),
    [
        (
            ScrapliTimeout("Timed out connecting to host raw-timeout-marker"),
            "device_connection_timeout",
            "DriverTimeoutError",
        ),
        (
            ScrapliAuthenticationFailed("Connection refused raw-refused-marker"),
            "device_connection_refused",
            "DriverConnectionRefusedError",
        ),
        (
            ScrapliConnectionError("encountered EOF reading from transport raw-eof-marker"),
            "device_connection_lost",
            "DriverConnectionLostError",
        ),
        (
            ScrapliAuthenticationFailed("Could not resolve address for host raw-resolution-marker"),
            "device_name_resolution_failed",
            "DriverNameResolutionError",
        ),
        (
            ScrapliAuthenticationFailed(
                "No ED25519 host key is known for edge-rtr-01.example.test raw-unknown-marker"
            ),
            "device_host_key_unknown",
            "DriverHostKeyUnknownError",
        ),
        (
            ScrapliAuthenticationFailed(
                "REMOTE HOST IDENTIFICATION HAS CHANGED raw-changed-marker"
            ),
            "device_host_key_changed",
            "DriverHostKeyChangedError",
        ),
    ],
)
def test_pinned_scrapli_failures_have_specific_stable_codes(
    error: Exception,
    expected_code: str,
    expected_type: str,
) -> None:
    translated = translate_ssh_error(error, phase=ConnectionPhase.TCP)
    error_type = getattr(core_errors, expected_type)

    assert type(translated) is error_type
    assert issubclass(error_type, DriverConnectionError | DriverTimeoutError)
    assert translated.code == expected_code
    assert "raw-" not in str(translated)
    assert "raw-" not in repr(translated.details)


@pytest.mark.parametrize(
    "marker",
    [
        "No matching key exchange found for host, their offer: raw-kex-offer",
        "No matching host key type found for host, their offer: raw-host-key-offer",
        "No matching cipher found for host, their offer: raw-cipher-offer",
    ],
)
def test_algorithm_mismatch_is_always_negotiation(marker: str) -> None:
    translated = translate_ssh_error(
        ScrapliAuthenticationFailed(marker),
        phase=ConnectionPhase.TCP,
    )

    assert type(translated) is DriverSSHNegotiationError
    assert translated.details == {
        "phase": "ssh_negotiation",
        "retryable": False,
        "recommended_action": _NEGOTIATION_ACTION,
    }
    assert "raw-" not in str(translated)
    assert "raw-" not in repr(translated.details)


@pytest.mark.parametrize(
    ("marker", "expected_type", "expected_code", "recommended_action"),
    [
        (
            "Host key verification failed raw-verification-marker",
            "DriverHostKeyVerificationError",
            "device_connection_failed",
            "Verify the saved SSH host key for this device.",
        ),
        (
            "REMOTE HOST IDENTIFICATION HAS CHANGED raw-changed-marker",
            "DriverHostKeyChangedError",
            "device_host_key_changed",
            "Verify the device identity before replacing its saved SSH host key.",
        ),
        (
            "No ED25519 host key is known for edge-rtr-01.example.test raw-unknown-marker",
            "DriverHostKeyUnknownError",
            "device_host_key_unknown",
            "Verify and enroll the device SSH host key.",
        ),
    ],
)
def test_real_host_key_failures_are_host_key_phase(
    marker: str,
    expected_type: str,
    expected_code: str,
    recommended_action: str,
) -> None:
    translated = translate_ssh_error(
        ScrapliAuthenticationFailed(marker),
        phase=ConnectionPhase.TCP,
    )

    assert type(translated) is getattr(core_errors, expected_type)
    assert isinstance(translated, DriverHostKeyVerificationError)
    assert translated.code == expected_code
    assert translated.details == {
        "phase": "host_key_verification",
        "retryable": False,
        "recommended_action": recommended_action,
    }
    assert "raw-" not in str(translated)
    assert "raw-" not in repr(translated.details)


@pytest.mark.parametrize(
    ("phase", "expected_code", "retryable"),
    [
        (ConnectionPhase.TCP, "device_connection_failed", True),
        (ConnectionPhase.NEGOTIATION, "legacy_ssh_negotiation_failed", False),
        (ConnectionPhase.HOST_KEY, "device_connection_failed", False),
        (ConnectionPhase.AUTHENTICATION, "device_authentication_failed", False),
        (ConnectionPhase.PTY, "terminal_pty_rejected", False),
        (ConnectionPhase.TERMINAL_IO, "terminal_transport_failed", True),
    ],
)
def test_generic_failures_use_the_phase_catalog(
    phase: ConnectionPhase,
    expected_code: str,
    retryable: bool,
) -> None:
    translated = translate_ssh_error(RuntimeError("raw-phase-marker"), phase=phase)

    assert translated.code == expected_code
    assert translated.details["phase"] == phase.value
    assert translated.details["retryable"] is retryable
    assert set(translated.details) <= {"phase", "retryable", "recommended_action"}
    assert "raw-phase-marker" not in str(translated)


@pytest.mark.parametrize("driver_type", [CiscoIOSXEDriver, GenericReadOnlyDriver])
def test_open_failures_default_to_tcp_for_both_adapters(driver_type) -> None:
    driver = driver_type(FakeTransportFactory({}, open_error=RuntimeError("raw-open-marker")))

    with pytest.raises(DriverConnectionError) as captured:
        driver.test_connection(parameters())

    assert captured.value.details["phase"] == "tcp_connection"
    rendered = "".join(traceback.format_exception(captured.type, captured.value, captured.tb))
    assert "raw-open-marker" not in rendered


def test_command_transport_failure_is_terminal_io_and_sanitized(
    sanitized_outputs: dict[str, str],
) -> None:
    driver = CiscoIOSXEDriver(
        FakeTransportFactory(
            sanitized_outputs,
            command_error=ScrapliConnectionError(
                "raw-command-marker edge-rtr-01.example.test fixture-password"
            ),
        )
    )

    with pytest.raises(DriverTerminalIOError) as captured:
        driver.run_diagnostic(parameters(), DiagnosticAction.ROUTING_TABLE)

    assert captured.value.code == "terminal_transport_failed"
    assert captured.value.details["phase"] == "terminal_io"
    rendered = "".join(traceback.format_exception(captured.type, captured.value, captured.tb))
    assert "raw-command-marker" not in rendered
    assert "edge-rtr-01.example.test" not in rendered
    assert "fixture-password" not in rendered


@pytest.mark.parametrize(
    "error",
    [
        DriverConnectionError("raw-typed-connection-marker"),
        DriverAuthenticationError("raw-typed-auth-marker"),
        ScrapliAuthenticationFailed("Permission denied raw-scrapli-auth-marker"),
        ScrapliConnectionError("encountered EOF reading from transport raw-scrapli-eof-marker"),
    ],
)
def test_command_connection_and_auth_failures_are_terminal_io(
    sanitized_outputs: dict[str, str],
    error: Exception,
) -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory(sanitized_outputs, command_error=error))

    with pytest.raises(DriverTerminalIOError) as captured:
        driver.run_diagnostic(parameters(), DiagnosticAction.ROUTING_TABLE)

    assert type(captured.value) is DriverTerminalIOError
    assert captured.value.code == "terminal_transport_failed"
    assert captured.value.details == {
        "phase": "terminal_io",
        "retryable": True,
        "recommended_action": "Retry the device operation after checking connectivity.",
    }
    assert "raw-" not in str(captured.value)


def test_typed_command_error_is_rebuilt_without_raw_state(
    sanitized_outputs: dict[str, str],
) -> None:
    raw_error = DriverCommandRejectedError(
        "raw-command-marker edge-rtr-01.example.test fixture-password"
    )
    driver = CiscoIOSXEDriver(
        FakeTransportFactory(
            sanitized_outputs,
            command_errors={"show version": raw_error},
        )
    )

    with pytest.raises(DriverCommandRejectedError) as captured:
        driver.collect_observations(parameters())

    assert captured.value is not raw_error
    assert captured.value.details == {
        "phase": "terminal_io",
        "retryable": False,
    }
    rendered = "".join(traceback.format_exception(captured.type, captured.value, captured.tb))
    assert "raw-command-marker" not in rendered
    assert "edge-rtr-01.example.test" not in rendered
    assert "fixture-password" not in rendered


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
    transport = ScrapliTransport(parameters())

    with pytest.raises(DriverCommandRejectedError):
        transport.send_command("show version")


def test_generic_transport_is_authenticated_but_vendor_neutral(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeGenericDriver:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def close(self) -> None:
            pass

    driver_module = SimpleNamespace(GenericDriver=FakeGenericDriver)
    monkeypatch.setitem(sys.modules, "scrapli.driver", driver_module)
    transport = ScrapliGenericTransport(parameters())

    assert "platform" not in captured
    assert captured["auth_username"] == "fixture-user"
    assert captured["timeout_socket"] == 7
    assert captured["timeout_ops"] == 41
    assert captured["auth_strict_key"] is True
    assert captured["transport"] == "system"
    transport.close()


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

    with pytest.raises(DriverTimeoutError) as neighbor_timeout:
        driver.get_neighbors(parameters())
    with pytest.raises(DriverTimeoutError) as diagnostic_timeout:
        driver.run_diagnostic(parameters(), DiagnosticAction.ROUTING_TABLE)

    for captured in (neighbor_timeout, diagnostic_timeout):
        assert captured.value.details == {
            "phase": "terminal_io",
            "retryable": True,
            "recommended_action": (
                "Retry after verifying device reachability and network latency."
            ),
        }


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
