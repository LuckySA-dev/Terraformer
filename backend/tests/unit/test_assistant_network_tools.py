"""The tools that let the assistant see the network rather than one device.

Before these it could only read a device whose id it had already been handed,
so "what does this network look like" was unanswerable -- there was no way to
enumerate devices at all, and adjacencies were stored per device with nothing
correlating the far ends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.assistant.tools import READ_ONLY_TOOLS, ReadOnlyToolError, ToolDispatcher

SW1 = UUID("11111111-1111-4111-8111-111111111111")
SW2 = UUID("22222222-2222-4222-8222-222222222222")


@dataclass
class _Vendor:
    value: str = "cisco_iosxe"


@dataclass
class _Status:
    value: str = "reachable"


@dataclass
class _FakeDevice:
    id: UUID
    name: str
    management_address: str
    facts: dict[str, Any] = field(default_factory=dict)
    is_lab: bool = False
    last_seen_at: datetime | None = None
    vendor: _Vendor = field(default_factory=_Vendor)
    status: _Status = field(default_factory=_Status)


@dataclass
class _FakeNeighbor:
    device_id: UUID
    protocol: str
    local_interface: str
    remote_device_name: str
    remote_interface: str
    management_address: str | None = None
    platform: str | None = None


class _FakeDevices:
    def __init__(self, devices: list[_FakeDevice], neighbors: dict[UUID, list[_FakeNeighbor]]):
        self._devices = devices
        self._neighbors = neighbors

    def list(self) -> list[_FakeDevice]:
        return self._devices

    def list_neighbors(self, device_id: UUID) -> list[_FakeNeighbor]:
        return self._neighbors.get(device_id, [])


def _network() -> _FakeDevices:
    devices = [
        _FakeDevice(
            id=SW1,
            name="SW1",
            management_address="192.0.2.11",
            facts={"hostname": "sw1", "model": "WS-C2960X-24TS"},
            last_seen_at=datetime(2026, 8, 29, 1, 0, tzinfo=UTC),
        ),
        _FakeDevice(id=SW2, name="SW2", management_address="192.0.2.12"),
    ]
    neighbors = {
        # Matched on the far end's management address.
        SW1: [
            _FakeNeighbor(
                device_id=SW1,
                protocol="cdp",
                local_interface="GigabitEthernet0/1",
                remote_device_name="sw2.example.test",
                remote_interface="GigabitEthernet0/2",
                management_address="192.0.2.12",
            ),
            # No far end in inventory: an observed-only neighbour.
            _FakeNeighbor(
                device_id=SW1,
                protocol="lldp",
                local_interface="GigabitEthernet0/24",
                remote_device_name="core-rtr-99",
                remote_interface="Gi0/0/1",
                management_address="198.51.100.9",
            ),
        ],
        # Matched on the hostname prefix instead, since CDP reports an FQDN
        # while the device is registered as "SW1".
        SW2: [
            _FakeNeighbor(
                device_id=SW2,
                protocol="cdp",
                local_interface="GigabitEthernet0/2",
                remote_device_name="sw1.example.test",
                remote_interface="GigabitEthernet0/1",
            )
        ],
    }
    return _FakeDevices(devices, neighbors)


def _dispatcher(devices: _FakeDevices) -> ToolDispatcher:
    return ToolDispatcher(devices=devices, snapshots=None, events=None)  # type: ignore[arg-type]


# --- the tools stay read-only ----------------------------------------------


def test_the_new_tools_are_registered_and_still_read_only() -> None:
    names = {tool.name for tool in READ_ONLY_TOOLS}
    assert {"list_devices", "get_topology", "list_change_plans"} <= names
    write_markers = ("apply", "delete", "create", "update", "set", "write", "send")
    for tool in READ_ONLY_TOOLS:
        assert not any(marker in tool.name.lower() for marker in write_markers), tool.name


def test_the_network_wide_tools_need_no_device_id() -> None:
    # dispatch() used to demand a device_id before it looked at the tool name,
    # which would have made every one of these impossible to call.
    dispatcher = _dispatcher(_network())
    assert dispatcher.dispatch("list_devices", {}).payload["devices"]
    assert dispatcher.dispatch("get_topology", {}).payload["links"]


# --- list_devices ----------------------------------------------------------


def test_listing_devices_gives_the_model_the_ids_every_other_tool_needs() -> None:
    payload = _dispatcher(_network()).dispatch("list_devices", {}).payload
    devices = payload["devices"]
    assert isinstance(devices, list)
    first = devices[0]
    assert first["device_id"] == str(SW1)
    assert first["name"] == "SW1"
    assert first["model"] == "WS-C2960X-24TS"
    # How current the record is, so staleness can be stated rather than hidden.
    assert first["last_seen_at"] == "2026-08-29T01:00:00+00:00"
    assert devices[1]["last_seen_at"] is None


# --- get_topology ----------------------------------------------------------


def test_the_topology_correlates_neighbours_onto_registered_devices() -> None:
    payload = _dispatcher(_network()).dispatch("get_topology", {}).payload
    links = payload["links"]
    assert isinstance(links, list)
    assert len(links) == 2
    by_local = {link["local_device"]: link for link in links}
    # Matched on the management address.
    assert by_local["SW1"]["remote_device_id"] == str(SW2)
    # Matched on the hostname prefix of an FQDN.
    assert by_local["SW2"]["remote_device_id"] == str(SW1)


def test_a_neighbour_that_is_not_registered_is_kept_apart_not_invented() -> None:
    # Observed nodes are evidence, not inventory; presenting one as a device
    # would let the model propose changes against something it cannot reach.
    payload = _dispatcher(_network()).dispatch("get_topology", {}).payload
    observed = payload["observed_only_neighbours"]
    assert isinstance(observed, list)
    assert len(observed) == 1
    assert observed[0]["remote_name"] == "core-rtr-99"
    assert "remote_device_id" not in observed[0]


def test_the_topology_says_what_kind_of_claim_it_is_making() -> None:
    payload = _dispatcher(_network()).dispatch("get_topology", {}).payload
    assert payload["evidence"] == "OBSERVED"
    assert "last refresh" in str(payload["note"])


def test_a_network_with_no_neighbour_records_returns_devices_and_no_links() -> None:
    empty = _FakeDevices([_FakeDevice(id=SW1, name="SW1", management_address="192.0.2.11")], {})
    payload = _dispatcher(empty).dispatch("get_topology", {}).payload
    assert payload["links"] == []
    assert len(payload["devices"]) == 1  # type: ignore[arg-type]


# --- list_change_plans -----------------------------------------------------


@dataclass
class _FakeStep:
    change_type: _Vendor
    target: str
    previous_value: str | None
    desired_value: str


@dataclass
class _FakePlan:
    id: UUID
    device_id: UUID
    status: _Vendor
    risk: _Vendor
    source: _Vendor
    failure_code: str | None
    created_at: datetime
    applied_at: datetime | None
    steps: list[_FakeStep]


class _FakeChanges:
    def __init__(self, plans: list[_FakePlan]):
        self._plans = plans

    def list_by_device(self, device_id: UUID, *, limit: int = 50) -> list[_FakePlan]:
        return [plan for plan in self._plans if plan.device_id == device_id][:limit]


def _plan(device_id: UUID, day: int, status: str, failure: str | None) -> _FakePlan:
    return _FakePlan(
        id=uuid4(),
        device_id=device_id,
        status=_Vendor(status),
        risk=_Vendor("high"),
        source=_Vendor("manual"),
        failure_code=failure,
        created_at=datetime(2026, 8, day, tzinfo=UTC),
        applied_at=None,
        steps=[_FakeStep(_Vendor("vlan_name"), "10", "USERS", "STAFF")],
    )


def test_change_history_is_newest_first_across_every_device() -> None:
    # "Why is this broken" is usually answered by the last change, so the most
    # recent one must not be buried behind whichever device sorted first.
    changes = _FakeChanges([_plan(SW1, 20, "applied", None), _plan(SW2, 27, "failed", "boom")])
    dispatcher = ToolDispatcher(
        devices=_network(),  # type: ignore[arg-type]
        snapshots=None,  # type: ignore[arg-type]
        events=None,  # type: ignore[arg-type]
        changes=changes,  # type: ignore[arg-type]
    )
    plans = dispatcher.dispatch("list_change_plans", {}).payload["change_plans"]
    assert isinstance(plans, list)
    assert plans[0]["status"] == "failed"
    assert plans[0]["failure_code"] == "boom"
    assert plans[0]["change_type"] == "vlan_name"
    assert plans[0]["previous_value"] == "USERS"


def test_a_limit_a_model_asks_for_is_bounded() -> None:
    changes = _FakeChanges([_plan(SW1, 20, "applied", None)])
    dispatcher = ToolDispatcher(
        devices=_network(),  # type: ignore[arg-type]
        snapshots=None,  # type: ignore[arg-type]
        events=None,  # type: ignore[arg-type]
        changes=changes,  # type: ignore[arg-type]
    )
    # A model that asks for everything must not be able to have everything.
    plans = dispatcher.dispatch("list_change_plans", {"limit": 100_000}).payload["change_plans"]
    assert isinstance(plans, list)
    assert len(plans) <= 100


def test_change_history_reports_its_absence_rather_than_returning_nothing() -> None:
    dispatcher = _dispatcher(_network())
    with pytest.raises(ReadOnlyToolError):
        dispatcher.dispatch("list_change_plans", {})
