"""The three change types that finish dynamic routing.

Withdrawing a network statement, the RIP version, and one BGP neighbour.
"""

from __future__ import annotations

import pytest

from app.changes.risk import classify_risk
from app.changes.service import _post_check_ok, _previous_value
from app.changes.types import ChangeStepIntent
from app.drivers import CiscoIOSXEDriver
from app.drivers.base import ChangeContext, RoutingProcessFacts
from app.models import ChangeRisk, ChangeStep, ChangeType
from tests.fakes import FakeTransportFactory

_OSPF = RoutingProcessFacts(
    name="ospf 1",
    statements=("router-id 1.1.1.1", "network 10.0.0.0 0.0.0.255 area 0"),
)
_RIP_V2 = RoutingProcessFacts(name="rip", statements=("version 2", "network 10.0.0.0"))
_RIP_DEFAULT = RoutingProcessFacts(name="rip", statements=("network 10.0.0.0",))
_BGP = RoutingProcessFacts(
    name="bgp 65001", statements=("neighbor 192.0.2.2 remote-as 65002",)
)


def _driver() -> CiscoIOSXEDriver:
    return CiscoIOSXEDriver(FakeTransportFactory({}))


def _step(change_type: ChangeType, target: str, value: str) -> ChangeStepIntent:
    return ChangeStepIntent(change_type=change_type, target=target, desired_value=value)


def _applied(change_type: ChangeType, target: str, value: str) -> ChangeStep:
    return ChangeStep(
        change_type=change_type,
        target=target,
        desired_value=value,
        previous_value=None,
        rendered_commands="",
        inverse_commands="",
    )


# --- withdrawing a network statement ---------------------------------------


def test_removing_a_statement_puts_it_back_to_roll_back() -> None:
    rendered = _driver().render_change(
        _step(ChangeType.ROUTER_NETWORK_REMOVE, "ospf 1", "10.0.0.0 0.0.0.255 area 0"),
        ChangeContext(routing_processes=(_OSPF,)),
    )
    assert rendered.commands == ("router ospf 1", "no network 10.0.0.0 0.0.0.255 area 0")
    assert rendered.inverse_commands == ("router ospf 1", "network 10.0.0.0 0.0.0.255 area 0")


def test_withdrawing_a_statement_the_process_does_not_have_is_refused() -> None:
    # The command would do nothing, and its inverse would then add a statement
    # the device never had -- a rollback that makes a change rather than
    # undoing one.
    issues = _driver().validate_change(
        _step(ChangeType.ROUTER_NETWORK_REMOVE, "ospf 1", "192.168.9.0 0.0.0.255 area 0"),
        ChangeContext(routing_processes=(_OSPF,)),
    )
    assert issues
    assert "does not have" in issues[0]


def test_withdrawing_from_a_process_that_is_not_there_is_refused() -> None:
    issues = _driver().validate_change(
        _step(ChangeType.ROUTER_NETWORK_REMOVE, "ospf 9", "10.0.0.0 0.0.0.255 area 0"),
        ChangeContext(routing_processes=(_OSPF,)),
    )
    assert issues
    assert "not configured" in issues[0]


def test_a_removal_post_checks_on_the_statement_being_gone() -> None:
    step = _applied(ChangeType.ROUTER_NETWORK_REMOVE, "ospf 1", "10.0.0.0 0.0.0.255 area 0")
    after = RoutingProcessFacts(name="ospf 1", statements=("router-id 1.1.1.1",))
    assert _post_check_ok(step, ChangeContext(routing_processes=(after,)))
    # Still there means the device did not take it.
    assert not _post_check_ok(step, ChangeContext(routing_processes=(_OSPF,)))


def test_a_removal_is_always_high_risk() -> None:
    assert (
        classify_risk(
            ChangeType.ROUTER_NETWORK_REMOVE,
            current_admin_up=None,
            current_oper_up=None,
            desired_value="10.0.0.0 0.0.0.255 area 0",
            target="ospf 1",
            previous_value="ospf 1",
        )
        is ChangeRisk.HIGH
    )


# --- RIP version -----------------------------------------------------------


def test_changing_the_version_restores_the_previous_one() -> None:
    rendered = _driver().render_change(
        _step(ChangeType.ROUTER_RIP_VERSION, "rip", "1"),
        ChangeContext(routing_processes=(_RIP_V2,)),
    )
    assert rendered.commands == ("router rip", "version 1")
    assert rendered.inverse_commands == ("router rip", "version 2")


def test_a_process_at_the_device_default_rolls_back_to_the_default() -> None:
    # No `version` line means the device default, and the way back to a default
    # is the negation rather than a number.
    rendered = _driver().render_change(
        _step(ChangeType.ROUTER_RIP_VERSION, "rip", "2"),
        ChangeContext(routing_processes=(_RIP_DEFAULT,)),
    )
    assert rendered.inverse_commands == ("router rip", "no version")


def test_setting_the_version_on_a_device_without_rip_starts_it() -> None:
    rendered = _driver().render_change(
        _step(ChangeType.ROUTER_RIP_VERSION, "rip", "2"),
        ChangeContext(routing_processes=(_OSPF,)),
    )
    assert rendered.commands == ("router rip", "version 2")
    assert rendered.inverse_commands == ("no router rip",)


@pytest.mark.parametrize("value", ["", "3", "v2", "0", "2 no-validate"])
def test_a_version_that_is_not_one_or_two_is_refused(value: str) -> None:
    assert _driver().validate_change(
        _step(ChangeType.ROUTER_RIP_VERSION, "rip", value),
        ChangeContext(routing_processes=(_RIP_V2,)),
    )


def test_setting_the_version_it_already_has_is_refused() -> None:
    issues = _driver().validate_change(
        _step(ChangeType.ROUTER_RIP_VERSION, "rip", "2"),
        ChangeContext(routing_processes=(_RIP_V2,)),
    )
    assert issues
    assert "already at" in issues[0]


def test_the_version_diff_shows_what_the_process_runs_now() -> None:
    context = ChangeContext(routing_processes=(_RIP_V2,))
    assert _previous_value(ChangeType.ROUTER_RIP_VERSION, "rip", context) == "version 2"
    assert (
        _previous_value(ChangeType.ROUTER_RIP_VERSION, "rip", ChangeContext()) is None
    )


def test_the_version_post_check_reads_the_line_back() -> None:
    step = _applied(ChangeType.ROUTER_RIP_VERSION, "rip", "1")
    after = RoutingProcessFacts(name="rip", statements=("version 1",))
    assert _post_check_ok(step, ChangeContext(routing_processes=(after,)))
    assert not _post_check_ok(step, ChangeContext(routing_processes=(_RIP_V2,)))


def test_a_version_change_is_always_high_risk() -> None:
    # v1 and v2 do not interoperate, so this drops every adjacency the process
    # had; on a device without RIP it starts the protocol.
    assert (
        classify_risk(
            ChangeType.ROUTER_RIP_VERSION,
            current_admin_up=None,
            current_oper_up=None,
            desired_value="2",
            target="rip",
            previous_value="version 1",
        )
        is ChangeRisk.HIGH
    )


# --- BGP neighbour ---------------------------------------------------------


def test_a_first_neighbour_starts_bgp_and_rolls_back_by_removing_it() -> None:
    rendered = _driver().render_change(
        _step(ChangeType.BGP_NEIGHBOR, "bgp 65001", "192.0.2.2 remote-as 65002"),
        ChangeContext(routing_processes=(_OSPF,)),
    )
    assert rendered.commands == ("router bgp 65001", "neighbor 192.0.2.2 remote-as 65002")
    assert rendered.inverse_commands == ("no router bgp 65001",)


def test_adding_a_peer_to_a_running_process_removes_only_that_peer() -> None:
    rendered = _driver().render_change(
        _step(ChangeType.BGP_NEIGHBOR, "bgp 65001", "192.0.2.9 remote-as 65009"),
        ChangeContext(routing_processes=(_BGP,)),
    )
    assert rendered.commands == ("router bgp 65001", "neighbor 192.0.2.9 remote-as 65009")
    assert rendered.inverse_commands == ("router bgp 65001", "no neighbor 192.0.2.9")


def test_rehoming_a_peer_withdraws_it_first_and_the_rollback_restores_the_old_as() -> None:
    # IOS will not hold two remote-as values for one neighbour.
    rendered = _driver().render_change(
        _step(ChangeType.BGP_NEIGHBOR, "bgp 65001", "192.0.2.2 remote-as 65100"),
        ChangeContext(routing_processes=(_BGP,)),
    )
    assert rendered.commands == (
        "router bgp 65001",
        "no neighbor 192.0.2.2",
        "neighbor 192.0.2.2 remote-as 65100",
    )
    assert rendered.inverse_commands == (
        "router bgp 65001",
        "no neighbor 192.0.2.2",
        "neighbor 192.0.2.2 remote-as 65002",
    )


def test_a_second_local_as_is_refused() -> None:
    # IOS runs one BGP process and answers a second local AS with an error, so
    # it is caught here rather than sent to be rejected there.
    issues = _driver().validate_change(
        _step(ChangeType.BGP_NEIGHBOR, "bgp 65999", "192.0.2.9 remote-as 65009"),
        ChangeContext(routing_processes=(_BGP,)),
    )
    assert issues
    assert "one BGP process" in issues[0]


def test_a_peer_that_is_already_configured_the_same_way_is_refused() -> None:
    issues = _driver().validate_change(
        _step(ChangeType.BGP_NEIGHBOR, "bgp 65001", "192.0.2.2 remote-as 65002"),
        ChangeContext(routing_processes=(_BGP,)),
    )
    assert issues
    assert "already has" in issues[0]


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("bgp 0", "192.0.2.2 remote-as 65002"),
        ("ospf 1", "192.0.2.2 remote-as 65002"),
        ("bgp 65001", "192.0.2.2"),
        ("bgp 65001", "999.0.0.2 remote-as 65002"),
        ("bgp 65001", "192.0.2.2 remote-as 65002 shutdown"),
        # Nothing that could carry a second command past the preview.
        ("bgp 65001", "192.0.2.2 remote-as 65002\nhostname EVIL"),
    ],
)
def test_a_malformed_bgp_change_is_refused(target: str, value: str) -> None:
    assert _driver().validate_change(
        _step(ChangeType.BGP_NEIGHBOR, target, value),
        ChangeContext(routing_processes=(_BGP,)),
    )


def test_the_bgp_post_check_reads_the_neighbour_back() -> None:
    step = _applied(ChangeType.BGP_NEIGHBOR, "bgp 65001", "192.0.2.9 remote-as 65009")
    after = RoutingProcessFacts(
        name="bgp 65001",
        statements=("neighbor 192.0.2.2 remote-as 65002", "neighbor 192.0.2.9 remote-as 65009"),
    )
    assert _post_check_ok(step, ChangeContext(routing_processes=(after,)))
    assert not _post_check_ok(step, ChangeContext(routing_processes=(_BGP,)))


def test_a_bgp_change_is_always_high_risk() -> None:
    assert (
        classify_risk(
            ChangeType.BGP_NEIGHBOR,
            current_admin_up=None,
            current_oper_up=None,
            desired_value="192.0.2.9 remote-as 65009",
            target="bgp 65001",
            previous_value="bgp 65001",
        )
        is ChangeRisk.HIGH
    )
