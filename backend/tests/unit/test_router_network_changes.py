from __future__ import annotations

from pathlib import Path

import pytest

from app.changes.risk import classify_risk
from app.changes.service import _post_check_ok, _previous_value
from app.changes.types import ChangeStepIntent
from app.drivers import CiscoIOSXEDriver
from app.drivers.base import ChangeContext, RoutingProcessFacts
from app.drivers.cisco_iosxe import parse_routing_processes
from app.models import ChangeRisk, ChangeStep, ChangeType
from tests.fakes import FakeTransportFactory


@pytest.fixture
def processes() -> tuple[RoutingProcessFacts, ...]:
    fixture = Path(__file__).parents[1] / "fixtures" / "cisco_iosxe" / "router_processes.txt"
    return tuple(parse_routing_processes(fixture.read_text(encoding="utf-8")))


def _driver() -> CiscoIOSXEDriver:
    return CiscoIOSXEDriver(FakeTransportFactory({}))


def _step(process: str, statement: str) -> ChangeStepIntent:
    return ChangeStepIntent(
        change_type=ChangeType.ROUTER_NETWORK, target=process, desired_value=statement
    )


def _applied_step(process: str, statement: str) -> ChangeStep:
    return ChangeStep(
        change_type=ChangeType.ROUTER_NETWORK,
        target=process,
        desired_value=statement,
        previous_value=None,
        rendered_commands="",
        inverse_commands="",
    )


# --- parsing ---------------------------------------------------------------


def test_reads_each_router_block_with_its_statements(
    processes: tuple[RoutingProcessFacts, ...],
) -> None:
    assert [process.name for process in processes] == ["ospf 1", "rip", "eigrp 100"]
    ospf = processes[0]
    assert "router-id 1.1.1.1" in ospf.statements
    assert ospf.has_statement("network 10.0.0.0 0.0.0.255 area 0")


def test_a_statement_is_matched_on_its_tokens_not_its_spacing(
    processes: tuple[RoutingProcessFacts, ...],
) -> None:
    # IOS re-spaces what it is given. Comparing raw text would read a change
    # that took as one that did not, and roll it back.
    assert processes[0].has_statement("network   10.0.0.0  0.0.0.255   area 0")


def test_an_unindented_line_ends_a_block() -> None:
    parsed = parse_routing_processes("router ospf 1\n network 10.0.0.0 0.0.0.255 area 0\nend\n")
    assert len(parsed) == 1
    assert parsed[0].statements == ("network 10.0.0.0 0.0.0.255 area 0",)


# --- rendering -------------------------------------------------------------


def test_adding_to_a_running_process_removes_only_the_statement(
    processes: tuple[RoutingProcessFacts, ...],
) -> None:
    rendered = _driver().render_change(
        _step("ospf 1", "192.168.5.0 0.0.0.255 area 0"),
        ChangeContext(routing_processes=processes),
    )
    assert rendered.commands == (
        "router ospf 1",
        "network 192.168.5.0 0.0.0.255 area 0",
    )
    assert rendered.inverse_commands == (
        "router ospf 1",
        "no network 192.168.5.0 0.0.0.255 area 0",
    )


def test_starting_a_process_rolls_back_by_removing_the_process(
    processes: tuple[RoutingProcessFacts, ...],
) -> None:
    # Undoing a start is a removal, the same way naming a VLAN that did not
    # exist rolls back to `no vlan` rather than to a previous name.
    rendered = _driver().render_change(
        _step("ospf 7", "10.9.0.0 0.0.0.255 area 0"),
        ChangeContext(routing_processes=processes),
    )
    assert rendered.commands == ("router ospf 7", "network 10.9.0.0 0.0.0.255 area 0")
    assert rendered.inverse_commands == ("no router ospf 7",)


def test_rip_needs_no_process_id(processes: tuple[RoutingProcessFacts, ...]) -> None:
    rendered = _driver().render_change(
        _step("rip", "192.168.9.0"), ChangeContext(routing_processes=processes)
    )
    assert rendered.commands == ("router rip", "network 192.168.9.0")


def test_the_statement_is_normalised_before_it_is_sent(
    processes: tuple[RoutingProcessFacts, ...],
) -> None:
    rendered = _driver().render_change(
        _step("eigrp 100", "  10.1.0.0   0.0.255.255 "),
        ChangeContext(routing_processes=processes),
    )
    assert rendered.commands == ("router eigrp 100", "network 10.1.0.0 0.0.255.255")


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "process",
    ["ospf", "ospf 0", "ospf 70000", "bgp 65000", "rip 1", "ospf 1; reload", ""],
)
def test_a_malformed_process_is_refused(
    process: str, processes: tuple[RoutingProcessFacts, ...]
) -> None:
    assert _driver().validate_change(
        _step(process, "10.0.0.0 0.0.0.255 area 0"), ChangeContext(routing_processes=processes)
    )


@pytest.mark.parametrize(
    ("process", "statement"),
    [
        # OSPF needs the area; without it the line is a different command.
        ("ospf 1", "10.0.0.0 0.0.0.255"),
        # RIP takes a classful network only.
        ("rip", "10.0.0.0 0.0.0.255"),
        ("ospf 1", "999.0.0.0 0.0.0.255 area 0"),
        # The value is interpolated into a config line, so nothing that could
        # carry a second command may pass.
        ("ospf 1", "10.0.0.0 0.0.0.255 area 0\nhostname EVIL"),
        ("eigrp 100", "not-an-address"),
    ],
)
def test_a_malformed_network_statement_is_refused(
    process: str, statement: str, processes: tuple[RoutingProcessFacts, ...]
) -> None:
    assert _driver().validate_change(
        _step(process, statement), ChangeContext(routing_processes=processes)
    )


@pytest.mark.parametrize(
    ("process", "statement"),
    [
        ("ospf 1", "192.168.5.0 0.0.0.255 area 0"),
        ("ospf 1", "192.168.5.0 0.0.0.255 area 0.0.0.1"),
        ("rip", "192.168.9.0"),
        ("eigrp 100", "10.1.0.0"),
        ("eigrp 100", "10.1.0.0 0.0.255.255"),
    ],
)
def test_a_well_formed_statement_passes(
    process: str, statement: str, processes: tuple[RoutingProcessFacts, ...]
) -> None:
    assert (
        _driver().validate_change(
            _step(process, statement), ChangeContext(routing_processes=processes)
        )
        == []
    )


def test_a_statement_the_process_already_has_is_refused(
    processes: tuple[RoutingProcessFacts, ...],
) -> None:
    # It would change nothing, and its inverse would then remove a statement
    # this change did not add.
    issues = _driver().validate_change(
        _step("ospf 1", "10.0.0.0 0.0.0.255 area 0"),
        ChangeContext(routing_processes=processes),
    )
    assert issues
    assert "already has" in issues[0]


# --- diff, post-check and risk ---------------------------------------------


def test_the_diff_distinguishes_extending_a_process_from_starting_one(
    processes: tuple[RoutingProcessFacts, ...],
) -> None:
    context = ChangeContext(routing_processes=processes)
    assert _previous_value(ChangeType.ROUTER_NETWORK, "ospf 1", context) == "ospf 1"
    assert _previous_value(ChangeType.ROUTER_NETWORK, "ospf 7", context) is None


def test_the_post_check_confirms_the_statement_is_configured() -> None:
    context = ChangeContext(
        routing_processes=(
            RoutingProcessFacts(name="ospf 1", statements=("network 10.9.0.0 0.0.0.255 area 0",)),
        )
    )
    assert _post_check_ok(_applied_step("ospf 1", "10.9.0.0 0.0.0.255 area 0"), context)


def test_the_post_check_fails_when_the_process_never_took_the_statement() -> None:
    context = ChangeContext(routing_processes=(RoutingProcessFacts(name="ospf 1"),))
    assert not _post_check_ok(_applied_step("ospf 1", "10.9.0.0 0.0.0.255 area 0"), context)


def test_starting_a_routing_protocol_is_high_risk() -> None:
    assert (
        classify_risk(
            ChangeType.ROUTER_NETWORK,
            current_admin_up=None,
            current_oper_up=None,
            desired_value="10.9.0.0 0.0.0.255 area 0",
            target="ospf 7",
            previous_value=None,
        )
        is ChangeRisk.HIGH
    )


def test_a_statement_covering_every_interface_is_high_risk() -> None:
    # It enables the protocol on the management interface too, which can move
    # how this device is reached.
    assert (
        classify_risk(
            ChangeType.ROUTER_NETWORK,
            current_admin_up=None,
            current_oper_up=None,
            desired_value="0.0.0.0 255.255.255.255 area 0",
            target="ospf 1",
            previous_value="ospf 1",
        )
        is ChangeRisk.HIGH
    )


def test_extending_a_running_process_is_low_risk() -> None:
    assert (
        classify_risk(
            ChangeType.ROUTER_NETWORK,
            current_admin_up=None,
            current_oper_up=None,
            desired_value="192.168.5.0 0.0.0.255 area 0",
            target="ospf 1",
            previous_value="ospf 1",
        )
        is ChangeRisk.LOW
    )
