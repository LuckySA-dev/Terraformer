"""Every change type the config window can reach, through the real API.

The per-type suites each prove their own rendering. This one exists to catch
what those cannot: a type wired into the enum and the UI but not into
preview's reads, its risk rule or its diff -- which shows up as a 500, an empty
command list, or a rollback identical to the change it is supposed to undo.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.changes.service import ChangeService
from app.container import ApplicationContainer
from app.drivers.base import (
    DeviceFacts,
    InterfaceFacts,
    RoutingProcessFacts,
    StaticRouteFacts,
    SwitchportFacts,
    VlanFacts,
)
from app.drivers.cisco_iosxe import CiscoIOSXEDriver
from app.models import ChangeType
from app.services.devices import DeviceService
from app.services.snapshots import SnapshotService

_INTERFACES = [
    InterfaceFacts(
        name="GigabitEthernet1/0/1",
        description="old-uplink",
        admin_up=True,
        oper_up=False,
    )
]
_VLANS = [
    VlanFacts(vlan_id=1, name="default", status="active"),
    VlanFacts(vlan_id=10, name="USERS", status="active", ports=("Gi1/0/1",)),
    VlanFacts(vlan_id=20, name="VOICE", status="active"),
]
_SWITCHPORTS = [
    SwitchportFacts(
        name="Gi1/0/1",
        mode="static access",
        access_vlan=10,
        trunk_allowed="ALL",
        trunk_encapsulation="dot1q",
    )
]
_ROUTES = [
    StaticRouteFacts(
        destination="10.10.0.0",
        mask="255.255.0.0",
        next_hop="192.0.2.9",
        raw="ip route 10.10.0.0 255.255.0.0 192.0.2.9",
    )
]
_PROCESSES = [
    RoutingProcessFacts(
        name="ospf 1", statements=("network 10.0.0.0 0.0.0.255 area 0",)
    ),
    RoutingProcessFacts(name="rip", statements=("version 1",)),
    RoutingProcessFacts(name="bgp 65001", statements=("neighbor 192.0.2.2 remote-as 65002",)),
]

# One valid request per change type, as the config window would send it.
_REQUESTS: dict[ChangeType, tuple[str, str]] = {
    ChangeType.INTERFACE_DESCRIPTION: ("GigabitEthernet1/0/1", "new-uplink"),
    ChangeType.INTERFACE_ADMIN_STATE: ("GigabitEthernet1/0/1", "down"),
    ChangeType.VLAN_NAME: ("20", "PHONES"),
    ChangeType.INTERFACE_ACCESS_VLAN: ("GigabitEthernet1/0/1", "20"),
    ChangeType.INTERFACE_TRUNK_VLANS: ("GigabitEthernet1/0/1", "1,10,20"),
    ChangeType.STATIC_ROUTE: ("10.10.0.0/16", "192.0.2.30"),
    ChangeType.ROUTER_NETWORK: ("ospf 1", "192.168.5.0 0.0.0.255 area 0"),
    ChangeType.ROUTER_NETWORK_REMOVE: ("ospf 1", "10.0.0.0 0.0.0.255 area 0"),
    ChangeType.ROUTER_RIP_VERSION: ("rip", "2"),
    ChangeType.BGP_NEIGHBOR: ("bgp 65001", "192.0.2.9 remote-as 65009"),
    ChangeType.HOSTNAME: ("", "SW9-ACCESS"),
    ChangeType.DOMAIN_LOOKUP: ("", "off"),
}


@pytest.fixture
def switch(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    container.settings.structured_writes_enabled = True
    monkeypatch.setattr(CiscoIOSXEDriver, "get_interfaces", lambda self, p: list(_INTERFACES))
    monkeypatch.setattr(CiscoIOSXEDriver, "get_vlans", lambda self, p: list(_VLANS))
    monkeypatch.setattr(CiscoIOSXEDriver, "get_switchports", lambda self, p: list(_SWITCHPORTS))
    monkeypatch.setattr(CiscoIOSXEDriver, "get_static_routes", lambda self, p: list(_ROUTES))
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_routing_processes", lambda self, p: list(_PROCESSES)
    )
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_facts", lambda self, p: DeviceFacts(hostname="SW9")
    )
    monkeypatch.setattr(CiscoIOSXEDriver, "get_domain_lookup", lambda self, p: True)

    connection = {
        "management_address": "192.0.2.200",
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": str(credential_profile["id"]),
        "ssh_compatibility": "modern",
    }
    candidate = authenticated_client.post("/api/ssh-host-key-candidates", json=connection)
    assert candidate.status_code == 201, candidate.text
    created = authenticated_client.post(
        "/api/devices",
        json={"name": "SW9", **connection, "host_key_candidate_id": candidate.json()["id"]},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_every_change_type_has_a_request_in_this_suite() -> None:
    # A new change type must arrive here rather than quietly going uncovered.
    assert set(_REQUESTS) == set(ChangeType)


@pytest.mark.parametrize("change_type", list(ChangeType), ids=lambda item: item.value)
def test_a_valid_request_previews_into_a_reversible_plan(
    authenticated_client: TestClient,
    switch: str,
    change_type: ChangeType,
) -> None:
    target, desired_value = _REQUESTS[change_type]
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": switch,
            "change_type": change_type.value,
            "target": target,
            "desired_value": desired_value,
        },
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    step = plan["steps"][0]

    assert step["rendered_commands"].strip(), "a plan that sends nothing is not a change"
    # Level C's whole promise is that the change carries the commands that put
    # it back, and a rollback identical to the change undoes nothing.
    assert step["inverse_commands"].strip(), "a Level C change must carry an inverse"
    assert step["inverse_commands"] != step["rendered_commands"]
    assert plan["risk"] in ("low", "high")
    assert plan["status"] == "draft"
    assert plan["safety_level"] == "C"


@pytest.mark.parametrize("change_type", list(ChangeType), ids=lambda item: item.value)
def test_a_malformed_value_is_refused_without_a_server_error(
    authenticated_client: TestClient,
    switch: str,
    change_type: ChangeType,
) -> None:
    # A newline is the value every type must refuse: the commands are stored
    # newline-joined and split back into lines at apply time, so one here would
    # smuggle a second command into a batch the operator vetted at preview.
    # Punctuation alone is not malformed -- an interface description is free
    # text and may legitimately contain it.
    target, _ = _REQUESTS[change_type]
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": switch,
            "change_type": change_type.value,
            "target": target,
            "desired_value": "10\nhostname EVIL",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["issues"]


@pytest.mark.parametrize("change_type", list(ChangeType), ids=lambda item: item.value)
def test_a_malformed_target_is_refused_without_a_server_error(
    authenticated_client: TestClient,
    switch: str,
    change_type: ChangeType,
) -> None:
    if change_type is ChangeType.HOSTNAME:
        pytest.skip("hostname targets the device itself, so its target carries no meaning")
    if change_type is ChangeType.DOMAIN_LOOKUP:
        pytest.skip("domain lookup targets the device itself, so its target carries no meaning")
    _, desired_value = _REQUESTS[change_type]
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": switch,
            "change_type": change_type.value,
            "target": "!!! not a valid target !!!",
            "desired_value": desired_value,
        },
    )
    assert response.status_code in (404, 422), response.text


def _change_service(container: ApplicationContainer, session) -> ChangeService:
    devices = DeviceService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        vault=container.credential_vault,
        host_key_trust=container.host_key_trust,
        connection_gate=container.connection_gate,
    )
    return ChangeService(
        session,
        settings=container.settings,
        drivers=container.drivers,
        devices=devices,
        snapshots=SnapshotService(
            session, store=container.snapshot_store, devices=devices, drivers=container.drivers
        ),
    )


def test_an_applied_interface_change_updates_the_stored_interfaces(
    switch: str,
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stored copy is what every screen renders.

    Without this the change reached the device but the UI kept showing the old
    value until a separate refresh job ran, which reads as the apply having
    silently done nothing. Apply runs through the service here because the
    queue in tests records jobs rather than running them.
    """
    with container.session_factory() as session:
        service = _change_service(container, session)
        plan = service.preview(
            device_id=UUID(switch),
            change_type=ChangeType.INTERFACE_DESCRIPTION,
            target="GigabitEthernet1/0/1",
            desired_value="new-uplink",
        )
        # What the device reports once the change is on it -- the post-check
        # reads this, and it is the copy that should be stored.
        monkeypatch.setattr(
            CiscoIOSXEDriver,
            "get_interfaces",
            lambda self, p: [
                InterfaceFacts(
                    name="GigabitEthernet1/0/1",
                    description="new-uplink",
                    admin_up=True,
                    oper_up=True,
                )
            ],
        )
        service.apply(plan.id)

    with container.session_factory() as session:
        stored = DeviceService(
            session,
            settings=container.settings,
            drivers=container.drivers,
            vault=container.credential_vault,
            host_key_trust=container.host_key_trust,
            connection_gate=container.connection_gate,
        ).list_interfaces(UUID(switch))
    assert [item.description for item in stored] == ["new-uplink"]


def test_a_change_that_reads_no_port_leaves_the_interface_inventory_alone(
    switch: str,
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # replace_interfaces deletes the existing rows first, so persisting an
    # empty read would wipe the inventory for every global or VLAN change.
    stored_port = InterfaceFacts(
        name="GigabitEthernet1/0/1", description="seeded", admin_up=True, oper_up=True
    )
    monkeypatch.setattr(CiscoIOSXEDriver, "get_interfaces", lambda self, p: [stored_port])

    with container.session_factory() as session:
        service = _change_service(container, session)
        # Applying an interface change is what puts a row in the table.
        seed = service.preview(
            device_id=UUID(switch),
            change_type=ChangeType.INTERFACE_DESCRIPTION,
            target="GigabitEthernet1/0/1",
            desired_value="seeded",
        )
        assert service.apply(seed.id)["status"] == "applied"

        # A hostname change reads no port at all. Its own post-check reads
        # facts, so the device has to report the new name for the apply to
        # succeed -- otherwise this would be measuring a rollback.
        monkeypatch.setattr(
            CiscoIOSXEDriver, "get_facts", lambda self, p: DeviceFacts(hostname="SW9-ACCESS")
        )
        hostname = service.preview(
            device_id=UUID(switch),
            change_type=ChangeType.HOSTNAME,
            target="",
            desired_value="SW9-ACCESS",
        )
        assert service.apply(hostname.id)["status"] == "applied"

    with container.session_factory() as session:
        stored = DeviceService(
            session,
            settings=container.settings,
            drivers=container.drivers,
            vault=container.credential_vault,
            host_key_trust=container.host_key_trust,
            connection_gate=container.connection_gate,
        ).list_interfaces(UUID(switch))
    assert [item.name for item in stored] == ["GigabitEthernet1/0/1"]
