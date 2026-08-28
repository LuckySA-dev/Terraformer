from __future__ import annotations

import pytest

from app.changes.risk import classify_risk
from app.changes.types import ChangeStepIntent
from app.core.errors import UnsupportedCapabilityError
from app.drivers.base import ChangeContext, InterfaceFacts
from app.drivers.cisco_iosxe import CiscoIOSXEDriver
from app.models import ChangeRisk, ChangeType
from tests.fakes import FakeTransportFactory


def _step(value: str) -> ChangeStepIntent:
    # `target` is meaningless for a global change; it is passed empty on
    # purpose so a renderer that quietly relied on it would fail here.
    return ChangeStepIntent(change_type=ChangeType.HOSTNAME, target="", desired_value=value)


def test_rollback_restores_the_name_the_device_reported() -> None:
    rendered = CiscoIOSXEDriver(FakeTransportFactory({})).render_change(
        _step("SW2-ACCESS"), ChangeContext(hostname="SW2")
    )

    assert rendered.commands == ("hostname SW2-ACCESS",)
    assert rendered.inverse_commands == ("hostname SW2",)


def test_a_hostname_that_cannot_be_read_back_is_refused() -> None:
    # No current hostname means no inverse, and a Level C change with no
    # inverse is one this pipeline must not stage at all.
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    with pytest.raises(UnsupportedCapabilityError):
        driver.render_change(_step("SW2-ACCESS"), ChangeContext(hostname=None))


@pytest.mark.parametrize(
    "value",
    [
        "has space",
        "2960-access",          # IOS hostnames start with a letter
        "sw2;reload",           # the injection this validation exists for
        "sw2\nshutdown",
        "",
        "a" * 64,
    ],
)
def test_invalid_hostnames_are_rejected_before_anything_is_rendered(value: str) -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    assert driver.validate_change(_step(value), ChangeContext(hostname="SW2"))


@pytest.mark.parametrize("value", ["SW2", "sw2-access", "Core1"])
def test_valid_hostnames_pass(value: str) -> None:
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    assert driver.validate_change(_step(value), ChangeContext(hostname="SW2")) == []


def test_renaming_the_device_is_low_risk_even_on_a_live_port() -> None:
    # A global change carries no interface state, so it must not inherit the
    # shared "live interface is HIGH" rule from unrelated arguments.
    assert classify_risk(
        ChangeType.HOSTNAME,
        current_admin_up=True,
        current_oper_up=True,
        desired_value="SW2-ACCESS",
    ) is ChangeRisk.LOW


def test_an_interface_change_on_a_live_port_stays_high() -> None:
    assert classify_risk(
        ChangeType.INTERFACE_DESCRIPTION,
        current_admin_up=True,
        current_oper_up=True,
        desired_value="uplink",
    ) is ChangeRisk.HIGH


def test_unused_interface_facts_do_not_leak_into_a_global_render() -> None:
    context = ChangeContext(
        interface=InterfaceFacts(
            name="Gi0/1", description="x", admin_up=True, oper_up=True
        ),
        hostname="SW2",
    )
    driver = CiscoIOSXEDriver(FakeTransportFactory({}))
    rendered = driver.render_change(_step("SW2-ACCESS"), context)
    assert all("interface" not in command for command in rendered.commands)
