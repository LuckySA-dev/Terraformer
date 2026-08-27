from __future__ import annotations

from pathlib import Path

import pytest

from app.changes.risk import classify_risk
from app.changes.types import ChangeStepIntent, normalize_interface_name
from app.drivers import CiscoIOSXEDriver, InterfaceFacts
from app.drivers.base import ChangeContext, VlanFacts
from app.drivers.cisco_iosxe import parse_show_vlan_brief
from app.models import ChangeRisk, ChangeType
from tests.fakes import FakeTransportFactory


@pytest.fixture
def vlan_output() -> str:
    fixture = Path(__file__).parents[1] / "fixtures" / "cisco_iosxe" / "show_vlan_brief.txt"
    return fixture.read_text(encoding="utf-8")


@pytest.fixture
def vlans(vlan_output: str) -> tuple[VlanFacts, ...]:
    return tuple(parse_show_vlan_brief(vlan_output))


def _driver() -> CiscoIOSXEDriver:
    return CiscoIOSXEDriver(FakeTransportFactory({}))


# --- parsing ---------------------------------------------------------------


def test_parses_the_vlan_table(vlans: tuple[VlanFacts, ...]) -> None:
    by_id = {vlan.vlan_id: vlan for vlan in vlans}
    assert by_id[10].name == "USERS"
    assert by_id[10].ports == ("Gi1/0/1", "Gi1/0/2")
    assert by_id[30].ports == ()


def test_a_wrapped_port_list_is_not_truncated(vlans: tuple[VlanFacts, ...]) -> None:
    # VLAN 1's ports continue onto a second line. Losing the continuation
    # would silently under-report membership, which is what the rollback
    # command for an access-VLAN move is built from.
    default = next(vlan for vlan in vlans if vlan.vlan_id == 1)
    assert "Gi1/0/10" in default.ports
    assert "Gi1/0/11" in default.ports


def test_the_header_row_is_not_read_as_a_vlan(vlans: tuple[VlanFacts, ...]) -> None:
    assert all(isinstance(vlan.vlan_id, int) for vlan in vlans)
    assert 1 in {vlan.vlan_id for vlan in vlans}


# --- port name normalisation ----------------------------------------------


def test_short_and_long_interface_spellings_match() -> None:
    # `show vlan brief` says Gi1/0/1 while `show interfaces` says
    # GigabitEthernet1/0/1; membership lookups compare the two.
    assert normalize_interface_name("GigabitEthernet1/0/1") == normalize_interface_name("Gi1/0/1")
    assert normalize_interface_name("TenGigabitEthernet1/1") == normalize_interface_name("Te1/1")


def test_access_vlan_lookup_survives_the_spelling_difference(
    vlans: tuple[VlanFacts, ...],
) -> None:
    context = ChangeContext(vlans=vlans)
    found = context.access_vlan_of("GigabitEthernet1/0/1")
    assert found is not None
    assert found.vlan_id == 10


# --- rendering -------------------------------------------------------------


def test_naming_an_existing_vlan_rolls_back_to_the_old_name(
    vlans: tuple[VlanFacts, ...],
) -> None:
    rendered = _driver().render_change(
        ChangeStepIntent(ChangeType.VLAN_NAME, "10", "STAFF"),
        ChangeContext(vlans=vlans),
    )

    assert rendered.commands == ("vlan 10", "name STAFF")
    assert rendered.inverse_commands == ("vlan 10", "name USERS")


def test_naming_a_new_vlan_rolls_back_by_deleting_it(vlans: tuple[VlanFacts, ...]) -> None:
    # Creating VLAN 40 means the undo is removing it. Renaming an existing
    # VLAN must never do that -- covered by the test above.
    rendered = _driver().render_change(
        ChangeStepIntent(ChangeType.VLAN_NAME, "40", "GUEST"),
        ChangeContext(vlans=vlans),
    )

    assert rendered.commands == ("vlan 40", "name GUEST")
    assert rendered.inverse_commands == ("no vlan 40",)


def test_moving_an_access_port_rolls_back_to_its_previous_vlan(
    vlans: tuple[VlanFacts, ...],
) -> None:
    rendered = _driver().render_change(
        ChangeStepIntent(ChangeType.INTERFACE_ACCESS_VLAN, "GigabitEthernet1/0/1", "20"),
        ChangeContext(vlans=vlans),
    )

    assert rendered.commands == (
        "interface GigabitEthernet1/0/1",
        "switchport mode access",
        "switchport access vlan 20",
    )
    assert rendered.inverse_commands == (
        "interface GigabitEthernet1/0/1",
        "switchport access vlan 10",
    )


def test_a_port_in_no_vlan_rolls_back_by_clearing_the_assignment(
    vlans: tuple[VlanFacts, ...],
) -> None:
    rendered = _driver().render_change(
        ChangeStepIntent(ChangeType.INTERFACE_ACCESS_VLAN, "GigabitEthernet1/0/48", "20"),
        ChangeContext(vlans=vlans),
    )

    assert rendered.inverse_commands == (
        "interface GigabitEthernet1/0/48",
        "no switchport access vlan",
    )


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "expected"),
    [("0", "between"), ("4095", "between"), ("abc", "must be a number"), ("1002", "reserved")],
)
def test_a_bad_vlan_id_is_rejected(target: str, expected: str) -> None:
    issues = _driver().validate_change(
        ChangeStepIntent(ChangeType.VLAN_NAME, target, "NAME"), ChangeContext()
    )
    assert any(expected in issue for issue in issues), issues


@pytest.mark.parametrize("name", ["has space", "semi;colon", "", "x" * 33])
def test_a_bad_vlan_name_is_rejected(name: str) -> None:
    issues = _driver().validate_change(
        ChangeStepIntent(ChangeType.VLAN_NAME, "10", name), ChangeContext()
    )
    assert issues != []


def test_a_vlan_name_cannot_smuggle_a_second_command() -> None:
    # The name is interpolated into a config line that is stored newline-
    # joined and split apart again at apply time.
    issues = _driver().validate_change(
        ChangeStepIntent(ChangeType.VLAN_NAME, "10", "OK\nno vlan 1"), ChangeContext()
    )
    assert issues != []


def test_assigning_a_port_to_a_missing_vlan_is_refused(
    vlans: tuple[VlanFacts, ...],
) -> None:
    # Assigning a port to a VLAN the switch does not have black-holes it.
    issues = _driver().validate_change(
        ChangeStepIntent(ChangeType.INTERFACE_ACCESS_VLAN, "GigabitEthernet1/0/1", "999"),
        ChangeContext(vlans=vlans),
    )
    assert any("does not exist" in issue for issue in issues), issues


def test_assigning_a_port_to_an_existing_vlan_is_accepted(
    vlans: tuple[VlanFacts, ...],
) -> None:
    assert (
        _driver().validate_change(
            ChangeStepIntent(ChangeType.INTERFACE_ACCESS_VLAN, "GigabitEthernet1/0/1", "20"),
            ChangeContext(vlans=vlans),
        )
        == []
    )


# --- risk ------------------------------------------------------------------


def test_renaming_a_vlan_stays_low_risk_even_on_a_live_port() -> None:
    assert (
        classify_risk(
            ChangeType.VLAN_NAME,
            current_admin_up=True,
            current_oper_up=True,
            desired_value="STAFF",
        )
        is ChangeRisk.LOW
    )


def test_moving_a_live_access_port_is_high_risk() -> None:
    assert (
        classify_risk(
            ChangeType.INTERFACE_ACCESS_VLAN,
            current_admin_up=True,
            current_oper_up=True,
            desired_value="20",
        )
        is ChangeRisk.HIGH
    )


def test_moving_a_dark_access_port_is_low_risk() -> None:
    assert (
        classify_risk(
            ChangeType.INTERFACE_ACCESS_VLAN,
            current_admin_up=True,
            current_oper_up=False,
            desired_value="20",
        )
        is ChangeRisk.LOW
    )


# --- driver read -----------------------------------------------------------


def test_get_vlans_returns_an_empty_table_when_the_device_has_no_vlans() -> None:
    # A router rejects `show vlan brief`; that must not fail a preview.
    from app.core.errors import DriverCommandRejectedError

    class _RejectingFactory(FakeTransportFactory):
        def __call__(self, parameters):  # type: ignore[no-untyped-def]
            raise DriverCommandRejectedError("Invalid input detected")

    driver = CiscoIOSXEDriver(_RejectingFactory({}))
    from app.drivers import ConnectionParameters

    assert (
        driver.get_vlans(
            ConnectionParameters(host="192.0.2.1", port=22, username="u", password="p")
        )
        == []
    )


def test_interface_context_still_works_for_non_vlan_changes() -> None:
    rendered = _driver().render_change(
        ChangeStepIntent(ChangeType.INTERFACE_DESCRIPTION, "GigabitEthernet1", "uplink"),
        ChangeContext(interface=InterfaceFacts(name="GigabitEthernet1", description="old")),
    )
    assert rendered.commands == ("interface GigabitEthernet1", "description uplink")
    assert rendered.inverse_commands == ("interface GigabitEthernet1", "description old")
