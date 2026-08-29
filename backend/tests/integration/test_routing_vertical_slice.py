"""Routing changes end to end: preview, apply, post-check, rollback.

Goes through the HTTP API and the real job runner, so it covers the wiring
between the driver read, the renderer, the risk rule and the post-check --
which is where a change type built in pieces tends to be broken.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.container import ApplicationContainer
from app.drivers.base import RoutingProcessFacts, StaticRouteFacts
from app.drivers.cisco_iosxe import CiscoIOSXEDriver
from app.jobs import tasks

_PROCESSES = (
    RoutingProcessFacts(
        name="ospf 1",
        statements=("router-id 1.1.1.1", "network 10.0.0.0 0.0.0.255 area 0"),
    ),
    RoutingProcessFacts(name="rip", statements=("version 2", "network 10.0.0.0")),
    RoutingProcessFacts(name="bgp 65001", statements=("neighbor 192.0.2.2 remote-as 65002",)),
)
_ROUTES = (
    StaticRouteFacts(
        destination="10.10.0.0",
        mask="255.255.0.0",
        next_hop="192.0.2.9",
        raw="ip route 10.10.0.0 255.255.0.0 192.0.2.9",
    ),
)


def _register_cisco(client: TestClient, profile_id: str, address: str) -> str:
    connection = {
        "management_address": address,
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": profile_id,
        "ssh_compatibility": "modern",
    }
    candidate = client.post("/api/ssh-host-key-candidates", json=connection)
    assert candidate.status_code == 201, candidate.text
    created = client.post(
        "/api/devices",
        json={
            "name": f"rtr-{address}",
            **connection,
            "host_key_candidate_id": candidate.json()["id"],
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


@pytest.fixture
def router(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    container.settings.structured_writes_enabled = True
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_routing_processes", lambda self, parameters: list(_PROCESSES)
    )
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_static_routes", lambda self, parameters: list(_ROUTES)
    )

    def _register(address: str) -> str:
        return _register_cisco(authenticated_client, str(credential_profile["id"]), address)

    return _register


def _preview(client: TestClient, device_id: str, **change: str) -> dict:
    response = client.post("/api/change-plans", json={"device_id": device_id, **change})
    assert response.status_code == 201, response.text
    return response.json()


def _run_apply(
    client: TestClient,
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
    plan_id: str,
) -> dict:
    queued = client.post(f"/api/change-plans/{plan_id}/apply")
    assert queued.status_code == 202, queued.text
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])
    return client.get(f"/api/change-plans/{plan_id}").json()


# --- OSPF ------------------------------------------------------------------


def test_adding_a_network_to_a_running_process_previews_and_applies(
    authenticated_client: TestClient,
    container: ApplicationContainer,
    router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = router("192.0.2.80")
    plan = _preview(
        authenticated_client,
        device_id,
        change_type="router_network",
        target="ospf 1",
        desired_value="192.168.5.0 0.0.0.255 area 0",
    )
    step = plan["steps"][0]
    assert step["rendered_commands"] == "router ospf 1\nnetwork 192.168.5.0 0.0.0.255 area 0"
    assert step["inverse_commands"] == "router ospf 1\nno network 192.168.5.0 0.0.0.255 area 0"
    # The process was already up, so this extends something the device was
    # already doing.
    assert step["previous_value"] == "ospf 1"
    assert plan["risk"] == "low"

    after = (
        RoutingProcessFacts(
            name="ospf 1",
            statements=(
                "network 10.0.0.0 0.0.0.255 area 0",
                "network 192.168.5.0 0.0.0.255 area 0",
            ),
        ),
    )
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_routing_processes", lambda self, parameters: list(after)
    )
    assert _run_apply(authenticated_client, container, monkeypatch, plan["id"])["status"] == (
        "applied"
    )


def test_starting_a_process_is_high_risk_and_rolls_back_by_removing_it(
    authenticated_client: TestClient,
    container: ApplicationContainer,
    router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = router("192.0.2.81")
    plan = _preview(
        authenticated_client,
        device_id,
        change_type="router_network",
        target="ospf 7",
        desired_value="10.9.0.0 0.0.0.255 area 0",
    )
    step = plan["steps"][0]
    assert step["previous_value"] is None
    assert step["inverse_commands"] == "no router ospf 7"
    # Putting the device into a routing domain it was not in.
    assert plan["risk"] == "high"

    # get_routing_processes still reports only "ospf 1", so the post-check
    # cannot confirm the change and the plan must not report success.
    settled = _run_apply(authenticated_client, container, monkeypatch, plan["id"])
    assert settled["status"] in ("rolled_back", "rollback_failed")
    assert settled["failure_code"] == "post_check_failed"


def test_a_statement_the_process_already_has_is_rejected_at_preview(
    authenticated_client: TestClient,
    router,
) -> None:
    device_id = router("192.0.2.82")
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "router_network",
            "target": "ospf 1",
            "desired_value": "10.0.0.0 0.0.0.255 area 0",
        },
    )
    assert response.status_code == 422, response.text
    assert any("already has" in issue for issue in response.json()["error"]["details"]["issues"])


def test_a_network_statement_without_an_area_is_rejected_for_ospf(
    authenticated_client: TestClient,
    router,
) -> None:
    device_id = router("192.0.2.83")
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "router_network",
            "target": "ospf 1",
            "desired_value": "192.168.5.0 0.0.0.255",
        },
    )
    assert response.status_code == 422, response.text


# --- static routes ---------------------------------------------------------


def test_repointing_a_static_route_previews_the_withdrawal_and_applies(
    authenticated_client: TestClient,
    container: ApplicationContainer,
    router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = router("192.0.2.84")
    plan = _preview(
        authenticated_client,
        device_id,
        change_type="static_route",
        target="10.10.0.0/16",
        desired_value="192.0.2.30",
    )
    step = plan["steps"][0]
    assert step["previous_value"] == "192.0.2.9"
    assert step["rendered_commands"] == (
        "no ip route 10.10.0.0 255.255.0.0 192.0.2.9\nip route 10.10.0.0 255.255.0.0 192.0.2.30"
    )
    assert step["inverse_commands"] == (
        "no ip route 10.10.0.0 255.255.0.0 192.0.2.30\nip route 10.10.0.0 255.255.0.0 192.0.2.9"
    )
    # Moving whatever was using the old path.
    assert plan["risk"] == "high"

    after = (
        StaticRouteFacts(
            destination="10.10.0.0",
            mask="255.255.0.0",
            next_hop="192.0.2.30",
            raw="ip route 10.10.0.0 255.255.0.0 192.0.2.30",
        ),
    )
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_static_routes", lambda self, parameters: list(after)
    )
    assert _run_apply(authenticated_client, container, monkeypatch, plan["id"])["status"] == (
        "applied"
    )


def test_a_default_route_is_flagged_high_even_though_nothing_routed_it_before(
    authenticated_client: TestClient,
    router,
) -> None:
    device_id = router("192.0.2.85")
    plan = _preview(
        authenticated_client,
        device_id,
        change_type="static_route",
        # A default route: the prefix, not an address anything binds to.
        target="0.0.0.0/0",
        desired_value="192.0.2.1",
    )
    assert plan["steps"][0]["previous_value"] is None
    assert plan["risk"] == "high"


# --- withdrawing a network statement ---------------------------------------


def test_removing_a_network_previews_the_withdrawal_and_applies(
    authenticated_client: TestClient,
    container: ApplicationContainer,
    router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = router("192.0.2.86")
    plan = _preview(
        authenticated_client,
        device_id,
        change_type="router_network_remove",
        target="ospf 1",
        desired_value="10.0.0.0 0.0.0.255 area 0",
    )
    step = plan["steps"][0]
    assert step["rendered_commands"] == "router ospf 1\nno network 10.0.0.0 0.0.0.255 area 0"
    assert step["inverse_commands"] == "router ospf 1\nnetwork 10.0.0.0 0.0.0.255 area 0"
    # Whatever reached that network through this device stops reaching it.
    assert plan["risk"] == "high"

    after = (RoutingProcessFacts(name="ospf 1", statements=("router-id 1.1.1.1",)),)
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_routing_processes", lambda self, parameters: list(after)
    )
    assert _run_apply(authenticated_client, container, monkeypatch, plan["id"])["status"] == (
        "applied"
    )


def test_withdrawing_a_statement_that_is_not_there_is_rejected_at_preview(
    authenticated_client: TestClient,
    router,
) -> None:
    device_id = router("192.0.2.87")
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "router_network_remove",
            "target": "ospf 1",
            "desired_value": "192.168.9.0 0.0.0.255 area 0",
        },
    )
    assert response.status_code == 422, response.text
    assert any(
        "does not have" in issue for issue in response.json()["error"]["details"]["issues"]
    )


# --- RIP version -----------------------------------------------------------


def test_changing_the_rip_version_previews_and_applies(
    authenticated_client: TestClient,
    container: ApplicationContainer,
    router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = router("192.0.2.88")
    plan = _preview(
        authenticated_client,
        device_id,
        change_type="router_rip_version",
        target="rip",
        desired_value="1",
    )
    step = plan["steps"][0]
    assert step["previous_value"] == "version 2"
    assert step["rendered_commands"] == "router rip\nversion 1"
    assert step["inverse_commands"] == "router rip\nversion 2"
    # v1 and v2 do not interoperate.
    assert plan["risk"] == "high"

    after = (RoutingProcessFacts(name="rip", statements=("version 1", "network 10.0.0.0")),)
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_routing_processes", lambda self, parameters: list(after)
    )
    assert _run_apply(authenticated_client, container, monkeypatch, plan["id"])["status"] == (
        "applied"
    )


def test_setting_the_version_rip_already_runs_is_rejected(
    authenticated_client: TestClient,
    router,
) -> None:
    device_id = router("192.0.2.89")
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "router_rip_version",
            "target": "rip",
            "desired_value": "2",
        },
    )
    assert response.status_code == 422, response.text


# --- BGP -------------------------------------------------------------------


def test_adding_a_bgp_neighbour_previews_and_applies(
    authenticated_client: TestClient,
    container: ApplicationContainer,
    router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = router("192.0.2.90")
    plan = _preview(
        authenticated_client,
        device_id,
        change_type="bgp_neighbor",
        target="bgp 65001",
        desired_value="192.0.2.9 remote-as 65009",
    )
    step = plan["steps"][0]
    assert step["rendered_commands"] == "router bgp 65001\nneighbor 192.0.2.9 remote-as 65009"
    assert step["inverse_commands"] == "router bgp 65001\nno neighbor 192.0.2.9"
    # A session can move a lot of reachability the moment it comes up.
    assert plan["risk"] == "high"

    after = (
        RoutingProcessFacts(
            name="bgp 65001",
            statements=(
                "neighbor 192.0.2.2 remote-as 65002",
                "neighbor 192.0.2.9 remote-as 65009",
            ),
        ),
    )
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_routing_processes", lambda self, parameters: list(after)
    )
    assert _run_apply(authenticated_client, container, monkeypatch, plan["id"])["status"] == (
        "applied"
    )


def test_a_second_bgp_local_as_is_rejected_at_preview(
    authenticated_client: TestClient,
    router,
) -> None:
    # IOS allows one BGP process per device.
    device_id = router("192.0.2.91")
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "bgp_neighbor",
            "target": "bgp 65999",
            "desired_value": "192.0.2.9 remote-as 65009",
        },
    )
    assert response.status_code == 422, response.text
    assert any(
        "one BGP process" in issue for issue in response.json()["error"]["details"]["issues"]
    )
