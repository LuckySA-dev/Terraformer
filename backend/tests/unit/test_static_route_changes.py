from __future__ import annotations

from pathlib import Path

import pytest

from app.changes.risk import classify_risk
from app.changes.service import _post_check_ok, _previous_value
from app.changes.types import ChangeStepIntent, prefix_parts
from app.drivers import CiscoIOSXEDriver
from app.drivers.base import ChangeContext, StaticRouteFacts
from app.drivers.cisco_iosxe import parse_static_routes
from app.models import ChangeRisk, ChangeStep, ChangeType
from tests.fakes import FakeTransportFactory


@pytest.fixture
def routes() -> tuple[StaticRouteFacts, ...]:
    fixture = Path(__file__).parents[1] / "fixtures" / "cisco_iosxe" / "ip_route_lines.txt"
    return tuple(parse_static_routes(fixture.read_text(encoding="utf-8")))


def _driver() -> CiscoIOSXEDriver:
    return CiscoIOSXEDriver(FakeTransportFactory({}))


def _step(target: str, next_hop: str) -> ChangeStepIntent:
    return ChangeStepIntent(
        change_type=ChangeType.STATIC_ROUTE, target=target, desired_value=next_hop
    )


def _applied_step(target: str, next_hop: str) -> ChangeStep:
    return ChangeStep(
        change_type=ChangeType.STATIC_ROUTE,
        target=target,
        desired_value=next_hop,
        previous_value=None,
        rendered_commands="",
        inverse_commands="",
    )


# --- prefix handling -------------------------------------------------------


def test_a_cidr_prefix_becomes_the_dotted_pair_ios_wants() -> None:
    assert prefix_parts("10.10.0.0/16") == ("10.10.0.0", "255.255.0.0")
    # The S104 suppressions below are a default route's prefix and mask, not
    # an address anything binds to.
    assert prefix_parts("0.0.0.0/0") == ("0.0.0.0", "0.0.0.0")  # noqa: S104


def test_a_prefix_with_host_bits_set_is_refused(routes: tuple[StaticRouteFacts, ...]) -> None:
    # 10.10.0.5/16 is the most common way to get this wrong, and silently
    # rounding it down would route a different prefix than the one typed.
    issues = _driver().validate_change(
        _step("10.10.0.5/16", "192.0.2.1"), ChangeContext(static_routes=routes)
    )
    assert issues
    assert "host bits" in issues[0]


# --- parsing ---------------------------------------------------------------


def test_reads_every_global_route(routes: tuple[StaticRouteFacts, ...]) -> None:
    assert [route.destination for route in routes] == [
        "0.0.0.0",  # noqa: S104 -- the default route's destination, not a bind address
        "10.10.0.0",
        "172.16.5.0",
        "192.168.7.0",
    ]
    assert routes[2].next_hop == "GigabitEthernet0/1"


def test_a_vrf_route_is_skipped_rather_than_half_understood(
    routes: tuple[StaticRouteFacts, ...],
) -> None:
    # Reading a VRF route as a global one would build a rollback that edits
    # the wrong routing table.
    assert all(route.destination != "10.99.0.0" for route in routes)


def test_trailing_options_survive_into_the_inverse(
    routes: tuple[StaticRouteFacts, ...],
) -> None:
    # The route carries a distance and a name. Reassembling the command from
    # parsed fields would drop both, so the rollback would restore a route
    # that is subtly not the one that was there.
    named = next(route for route in routes if route.destination == "192.168.7.0")
    assert named.as_command() == "ip route 192.168.7.0 255.255.255.0 10.0.0.2 200 name BACKUP-PATH"


# --- rendering -------------------------------------------------------------


def test_routing_a_new_prefix_adds_one_line_and_removes_it_to_roll_back(
    routes: tuple[StaticRouteFacts, ...],
) -> None:
    rendered = _driver().render_change(
        _step("203.0.113.0/24", "192.0.2.1"), ChangeContext(static_routes=routes)
    )
    assert rendered.commands == ("ip route 203.0.113.0 255.255.255.0 192.0.2.1",)
    assert rendered.inverse_commands == ("no ip route 203.0.113.0 255.255.255.0 192.0.2.1",)


def test_repointing_a_prefix_withdraws_the_old_line_in_the_same_change(
    routes: tuple[StaticRouteFacts, ...],
) -> None:
    # Two `ip route` lines for one prefix are alternative paths, not an edit:
    # leaving the old one would install a second route beside the new one.
    rendered = _driver().render_change(
        _step("10.10.0.0/16", "192.0.2.30"), ChangeContext(static_routes=routes)
    )
    assert rendered.commands == (
        "no ip route 10.10.0.0 255.255.0.0 192.0.2.9",
        "ip route 10.10.0.0 255.255.0.0 192.0.2.30",
    )
    assert rendered.inverse_commands == (
        "no ip route 10.10.0.0 255.255.0.0 192.0.2.30",
        "ip route 10.10.0.0 255.255.0.0 192.0.2.9",
    )


def test_the_rollback_restores_the_options_the_route_had(
    routes: tuple[StaticRouteFacts, ...],
) -> None:
    rendered = _driver().render_change(
        _step("192.168.7.0/24", "10.0.0.9"), ChangeContext(static_routes=routes)
    )
    assert rendered.inverse_commands[1] == (
        "ip route 192.168.7.0 255.255.255.0 10.0.0.2 200 name BACKUP-PATH"
    )


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "next_hop",
    ["", "   ", "192.0.2.1 permanent", "192.0.2.1\nhostname EVIL", "-weird"],
)
def test_a_next_hop_that_is_not_one_word_is_refused(
    next_hop: str, routes: tuple[StaticRouteFacts, ...]
) -> None:
    # The value is interpolated into one config line that is split back into
    # lines at apply time, so anything carrying whitespace could smuggle a
    # second command into a batch the operator vetted at preview.
    assert _driver().validate_change(
        _step("203.0.113.0/24", next_hop), ChangeContext(static_routes=routes)
    )


@pytest.mark.parametrize("next_hop", ["192.0.2.1", "GigabitEthernet0/1", "Serial0/0/0:0"])
def test_an_address_or_an_exit_interface_is_accepted(
    next_hop: str, routes: tuple[StaticRouteFacts, ...]
) -> None:
    assert (
        _driver().validate_change(
            _step("203.0.113.0/24", next_hop), ChangeContext(static_routes=routes)
        )
        == []
    )


@pytest.mark.parametrize("target", ["10.10.0.0", "not-a-prefix", "10.10.0.0/33", ""])
def test_a_destination_that_is_not_a_prefix_is_refused(
    target: str, routes: tuple[StaticRouteFacts, ...]
) -> None:
    assert _driver().validate_change(
        _step(target, "192.0.2.1"), ChangeContext(static_routes=routes)
    )


# --- diff, post-check and risk ---------------------------------------------


def test_the_diff_shows_the_next_hop_the_prefix_had(
    routes: tuple[StaticRouteFacts, ...],
) -> None:
    context = ChangeContext(static_routes=routes)
    assert _previous_value(ChangeType.STATIC_ROUTE, "10.10.0.0/16", context) == "192.0.2.9"
    assert _previous_value(ChangeType.STATIC_ROUTE, "203.0.113.0/24", context) is None


def test_the_post_check_confirms_the_new_next_hop_is_configured() -> None:
    context = ChangeContext(
        static_routes=(
            StaticRouteFacts(
                destination="10.10.0.0", mask="255.255.0.0", next_hop="192.0.2.30"
            ),
        )
    )
    assert _post_check_ok(_applied_step("10.10.0.0/16", "192.0.2.30"), context)


def test_the_post_check_fails_when_the_old_next_hop_is_still_there(
    routes: tuple[StaticRouteFacts, ...],
) -> None:
    assert not _post_check_ok(
        _applied_step("10.10.0.0/16", "192.0.2.30"), ChangeContext(static_routes=routes)
    )


def test_a_default_route_is_high_risk() -> None:
    # It moves everything with no more specific match, which on a device
    # reached over that path includes the session applying the change.
    assert (
        classify_risk(
            ChangeType.STATIC_ROUTE,
            current_admin_up=None,
            current_oper_up=None,
            desired_value="192.0.2.1",
            target="0.0.0.0/0",
            previous_value=None,
        )
        is ChangeRisk.HIGH
    )


def test_repointing_an_existing_prefix_is_high_risk() -> None:
    assert (
        classify_risk(
            ChangeType.STATIC_ROUTE,
            current_admin_up=None,
            current_oper_up=None,
            desired_value="192.0.2.30",
            target="10.10.0.0/16",
            previous_value="192.0.2.9",
        )
        is ChangeRisk.HIGH
    )


def test_routing_a_prefix_nothing_routed_before_is_low_risk() -> None:
    assert (
        classify_risk(
            ChangeType.STATIC_ROUTE,
            current_admin_up=None,
            current_oper_up=None,
            desired_value="192.0.2.1",
            target="203.0.113.0/24",
            previous_value=None,
        )
        is ChangeRisk.LOW
    )
