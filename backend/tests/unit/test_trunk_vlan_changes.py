from __future__ import annotations

from pathlib import Path

import pytest

from app.changes.risk import classify_risk
from app.changes.service import _post_check_ok, _previous_value
from app.changes.types import ChangeStepIntent, expand_vlan_list, vlan_list_issues
from app.core.errors import UnsupportedCapabilityError
from app.drivers import CiscoIOSXEDriver, InterfaceFacts
from app.drivers.base import ChangeContext, SwitchportFacts
from app.drivers.cisco_iosxe import parse_show_interfaces_switchport
from app.models import ChangeRisk, ChangeStep, ChangeType
from tests.fakes import FakeTransportFactory


@pytest.fixture
def switchports() -> tuple[SwitchportFacts, ...]:
    fixture = (
        Path(__file__).parents[1] / "fixtures" / "cisco_iosxe" / "show_interfaces_switchport.txt"
    )
    return tuple(parse_show_interfaces_switchport(fixture.read_text(encoding="utf-8")))


def _driver() -> CiscoIOSXEDriver:
    return CiscoIOSXEDriver(FakeTransportFactory({}))


def _context(ports: tuple[SwitchportFacts, ...]) -> ChangeContext:
    return ChangeContext(
        interface=InterfaceFacts(name="GigabitEthernet1/0/24", admin_up=True, oper_up=True),
        switchports=ports,
    )


def _step(target: str, value: str) -> ChangeStepIntent:
    return ChangeStepIntent(
        change_type=ChangeType.INTERFACE_TRUNK_VLANS, target=target, desired_value=value
    )


def _applied_step(target: str, value: str) -> ChangeStep:
    return ChangeStep(
        change_type=ChangeType.INTERFACE_TRUNK_VLANS,
        target=target,
        desired_value=value,
        previous_value=None,
        rendered_commands="",
        inverse_commands="",
    )


# --- parsing ---------------------------------------------------------------


def test_reads_the_mode_and_allowed_list_of_every_port(
    switchports: tuple[SwitchportFacts, ...],
) -> None:
    by_name = {port.name: port for port in switchports}
    assert by_name["Gi1/0/1"].mode == "static access"
    assert by_name["Gi1/0/1"].access_vlan == 10
    assert by_name["Gi1/0/2"].mode == "dynamic auto"
    assert by_name["Gi1/0/24"].is_trunk()
    assert by_name["Gi1/0/24"].native_vlan == 99


def test_a_wrapped_allowed_list_is_not_truncated(
    switchports: tuple[SwitchportFacts, ...],
) -> None:
    # IOS breaks a long list after a comma and continues on the next line with
    # no label at all. Losing the continuation would build a rollback command
    # that silently narrows the trunk it was meant to restore.
    trunk = next(port for port in switchports if port.name == "Gi1/0/24")
    assert trunk.trunk_allowed is not None
    assert trunk.trunk_allowed.endswith("150,160,170,180")
    assert 180 in expand_vlan_list(trunk.trunk_allowed)


def test_a_routed_port_reports_no_layer_two_state(
    switchports: tuple[SwitchportFacts, ...],
) -> None:
    routed = next(port for port in switchports if port.name == "Gi1/0/25")
    assert not routed.is_trunk()
    assert routed.trunk_allowed is None


def test_the_short_name_matches_the_long_one(
    switchports: tuple[SwitchportFacts, ...],
) -> None:
    # This read abbreviates (Gi1/0/24) while `show interfaces` spells the name
    # out; a lookup that missed would refuse every change on the port.
    assert _context(switchports).switchport_of("GigabitEthernet1/0/24") is not None


# --- rendering -------------------------------------------------------------


def test_editing_a_trunk_sends_only_the_allowed_list(
    switchports: tuple[SwitchportFacts, ...],
) -> None:
    rendered = _driver().render_change(_step("Gi1/0/24", "1,10,20"), _context(switchports))
    assert rendered.commands == (
        "interface Gi1/0/24",
        "switchport trunk allowed vlan 1,10,20",
    )
    # The port was already trunking, so the inverse restores the list it had
    # and leaves the mode alone.
    assert len(rendered.inverse_commands) == 2
    assert rendered.inverse_commands[0] == "interface Gi1/0/24"
    assert rendered.inverse_commands[1].startswith("switchport trunk allowed vlan 1-5,10,20")


def test_a_non_trunk_port_is_put_into_trunk_mode_and_the_inverse_puts_it_back(
    switchports: tuple[SwitchportFacts, ...],
) -> None:
    # An allowed list does nothing on a port that is not trunking, and a fresh
    # switch has no trunks at all -- so the mode is part of the change, which
    # makes it part of the rollback.
    rendered = _driver().render_change(_step("Gi1/0/1", "10,20"), _context(switchports))
    assert rendered.commands == (
        "interface Gi1/0/1",
        "switchport mode trunk",
        "switchport trunk allowed vlan 10,20",
    )
    assert rendered.inverse_commands == (
        "interface Gi1/0/1",
        # The port carried the default ALL, whose way back is the negation
        # rather than a list.
        "no switchport trunk allowed vlan",
        "switchport mode access",
    )


def test_encapsulation_is_set_only_where_the_device_asked_for_it(
    switchports: tuple[SwitchportFacts, ...],
) -> None:
    # Gi1/0/2 reports "negotiate", which is the platform saying it also speaks
    # ISL and will refuse trunk mode until told which to use. Gi1/0/1 reports
    # dot1q, a platform where the same command does not exist.
    negotiating = _driver().render_change(_step("Gi1/0/2", "10"), _context(switchports))
    assert "switchport trunk encapsulation dot1q" in negotiating.commands
    dot1q_only = _driver().render_change(_step("Gi1/0/1", "10"), _context(switchports))
    assert "switchport trunk encapsulation dot1q" not in dot1q_only.commands


def test_a_port_with_no_readable_mode_is_refused_rather_than_staged() -> None:
    # No inverse means no rollback, and a Level C change without one is not
    # something this pipeline may run.
    context = ChangeContext(
        switchports=(SwitchportFacts(name="Gi1/0/9", mode="private-vlan promiscuous"),)
    )
    with pytest.raises(UnsupportedCapabilityError):
        _driver().render_change(_step("Gi1/0/9", "10"), context)


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["", "all", "10;20", "10-", "30-10", "0,10", "1-5000", "10, 20"],
)
def test_a_malformed_allowed_list_is_rejected(
    value: str, switchports: tuple[SwitchportFacts, ...]
) -> None:
    assert _driver().validate_change(_step("Gi1/0/24", value), _context(switchports))


def test_a_well_formed_list_passes(switchports: tuple[SwitchportFacts, ...]) -> None:
    assert _driver().validate_change(_step("Gi1/0/24", "1,10,20-30"), _context(switchports)) == []


def test_a_vlan_the_switch_does_not_have_is_allowed_on_a_trunk(
    switchports: tuple[SwitchportFacts, ...],
) -> None:
    # Unlike an access port, where a missing VLAN black-holes the port, a trunk
    # simply does not carry it. Refusing here would be friction with no failure
    # behind it.
    context = ChangeContext(switchports=switchports, vlans=())
    assert _driver().validate_change(_step("Gi1/0/24", "777"), context) == []


def test_an_unknown_port_is_refused(switchports: tuple[SwitchportFacts, ...]) -> None:
    assert _driver().validate_change(_step("Gi9/9/9", "10"), _context(switchports))


def test_reserved_vlans_are_allowed_on_a_trunk() -> None:
    # 1002-1005 cannot be renamed or assigned to an access port, but they sit
    # inside the default trunk range, so a list spanning them is not an error.
    assert vlan_list_issues("1-1005", field="allowed VLAN list") == []


# --- diff, post-check and risk ---------------------------------------------


def test_the_diff_says_all_rather_than_none_for_a_default_trunk() -> None:
    context = ChangeContext(
        switchports=(SwitchportFacts(name="Gi1/0/3", mode="trunk", trunk_allowed="ALL"),)
    )
    assert _previous_value(ChangeType.INTERFACE_TRUNK_VLANS, "Gi1/0/3", context) == "ALL"


def test_the_post_check_compares_ids_not_the_text_the_device_printed() -> None:
    # IOS reorders and re-ranges what it is given, so a text comparison would
    # fail a change that worked and then roll it back.
    context = ChangeContext(
        switchports=(SwitchportFacts(name="Gi1/0/4", mode="trunk", trunk_allowed="10-12,20"),)
    )
    assert _post_check_ok(_applied_step("Gi1/0/4", "20,10,11,12"), context)


def test_the_post_check_fails_when_the_port_never_became_a_trunk() -> None:
    context = ChangeContext(
        switchports=(SwitchportFacts(name="Gi1/0/5", mode="dynamic auto", trunk_allowed="10"),)
    )
    assert not _post_check_ok(_applied_step("Gi1/0/5", "10"), context)


def test_replacing_the_list_on_a_live_trunk_is_high_risk() -> None:
    # The list replaces rather than adds, so every VLAN it omits stops crossing
    # a link that is carrying traffic right now.
    assert (
        classify_risk(
            ChangeType.INTERFACE_TRUNK_VLANS,
            current_admin_up=True,
            current_oper_up=True,
            desired_value="10",
        )
        is ChangeRisk.HIGH
    )


def test_the_same_change_on_a_dark_port_is_low_risk() -> None:
    assert (
        classify_risk(
            ChangeType.INTERFACE_TRUNK_VLANS,
            current_admin_up=True,
            current_oper_up=False,
            desired_value="10",
        )
        is ChangeRisk.LOW
    )
