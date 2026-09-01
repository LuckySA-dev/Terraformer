from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.drivers.base import RoutingProcessFacts, StaticRouteFacts
from app.drivers.cisco_iosxe import CiscoIOSXEDriver

_ROUTES = [
    StaticRouteFacts(
        destination="10.10.0.0",
        mask="255.255.0.0",
        next_hop="192.0.2.30",
        raw="ip route 10.10.0.0 255.255.0.0 192.0.2.30 name to-lab",
    ),
]
_PROCESSES = [RoutingProcessFacts(name="ospf 1", statements=("network 10.0.0.0 0.0.0.255 area 0",))]


@pytest.fixture
def device_id(
    authenticated_client: TestClient, credential_profile, monkeypatch: pytest.MonkeyPatch
) -> str:
    monkeypatch.setattr(CiscoIOSXEDriver, "get_static_routes", lambda self, p: list(_ROUTES))
    monkeypatch.setattr(
        CiscoIOSXEDriver, "get_routing_processes", lambda self, p: list(_PROCESSES)
    )
    connection = {
        "management_address": "192.0.2.210",
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": str(credential_profile["id"]),
        "ssh_compatibility": "modern",
    }
    candidate = authenticated_client.post("/api/ssh-host-key-candidates", json=connection)
    created = authenticated_client.post(
        "/api/devices",
        json={"name": "R9", **connection, "host_key_candidate_id": candidate.json()["id"]},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_one_call_returns_both_halves(authenticated_client: TestClient, device_id: str) -> None:
    response = authenticated_client.get(f"/api/devices/{device_id}/routing")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["static_routes"]) == 1
    assert len(body["processes"]) == 1


def test_a_route_keeps_the_options_the_parser_does_not_model(
    authenticated_client: TestClient, device_id: str
) -> None:
    route = authenticated_client.get(f"/api/devices/{device_id}/routing").json()["static_routes"][0]

    assert route["destination"] == "10.10.0.0"
    assert route["next_hop"] == "192.0.2.30"
    # The table shows the line the device actually has, trailing `name` and
    # all -- reassembling it from the parsed fields would drop that.
    assert route["command"].endswith("name to-lab")


def test_a_process_carries_its_statements(
    authenticated_client: TestClient, device_id: str
) -> None:
    process = authenticated_client.get(f"/api/devices/{device_id}/routing").json()["processes"][0]

    assert process["name"] == "ospf 1"
    assert process["statements"] == ["network 10.0.0.0 0.0.0.255 area 0"]
