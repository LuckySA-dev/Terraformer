from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import ApplicationContainer
from app.drivers.base import VlanFacts
from app.drivers.cisco_iosxe import CiscoIOSXEDriver
from app.jobs import tasks


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
            "name": f"sw-{address}",
            **connection,
            "host_key_candidate_id": candidate.json()["id"],
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


_BEFORE = (
    VlanFacts(vlan_id=1, name="default", status="active", ports=("Gi1/0/9",)),
    VlanFacts(vlan_id=10, name="USERS", status="active", ports=("GigabitEthernet1",)),
    VlanFacts(vlan_id=20, name="VOICE", status="active", ports=()),
)


def test_vlan_rename_previews_with_a_diff_and_a_reversible_rollback(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    monkeypatch.setattr(CiscoIOSXEDriver, "get_vlans", lambda self, parameters: list(_BEFORE))
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.60")

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "vlan_name",
            "target": "10",
            "desired_value": "STAFF",
        },
    )

    assert response.status_code == 201, response.text
    plan = response.json()
    step = plan["steps"][0]
    assert step["previous_value"] == "USERS"
    assert step["desired_value"] == "STAFF"
    assert step["rendered_commands"] == "vlan 10\nname STAFF"
    assert step["inverse_commands"] == "vlan 10\nname USERS"
    # A rename moves no traffic.
    assert plan["risk"] == "low"


def test_a_vlan_rename_applies_and_post_checks_against_the_vlan_table(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    monkeypatch.setattr(CiscoIOSXEDriver, "get_vlans", lambda self, parameters: list(_BEFORE))
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.61")
    plan = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "vlan_name",
            "target": "10",
            "desired_value": "STAFF",
        },
    ).json()

    # The fake transport is a static lookup table, not a simulator, so the
    # post-apply read is patched to the state a real switch would then show.
    after = [
        VlanFacts(vlan_id=10, name="STAFF", status="active", ports=("GigabitEthernet1",)),
    ]
    monkeypatch.setattr(CiscoIOSXEDriver, "get_vlans", lambda self, parameters: after)

    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    assert queued.status_code == 202, queued.text
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    assert authenticated_client.get(f"/api/change-plans/{plan['id']}").json()["status"] == "applied"


def test_a_vlan_change_that_does_not_take_rolls_back(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    """The switch accepted the command but the VLAN table never changed."""
    container.settings.structured_writes_enabled = True
    monkeypatch.setattr(CiscoIOSXEDriver, "get_vlans", lambda self, parameters: list(_BEFORE))
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.62")
    plan = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "vlan_name",
            "target": "10",
            "desired_value": "STAFF",
        },
    ).json()

    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    # get_vlans still reports USERS, so the post-check must fail rather than
    # report a success the device never performed.
    assert authenticated_client.get(f"/api/change-plans/{plan['id']}").json()["status"] in (
        "rolled_back",
        "rollback_failed",
        "failed",
    )


def test_moving_an_access_port_previews_the_switchport_commands(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    monkeypatch.setattr(CiscoIOSXEDriver, "get_vlans", lambda self, parameters: list(_BEFORE))
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.63")

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_access_vlan",
            "target": "GigabitEthernet1",
            "desired_value": "20",
        },
    )

    assert response.status_code == 201, response.text
    step = response.json()["steps"][0]
    assert step["previous_value"] == "10"
    assert step["rendered_commands"] == (
        "interface GigabitEthernet1\nswitchport mode access\nswitchport access vlan 20"
    )
    assert step["inverse_commands"] == "interface GigabitEthernet1\nswitchport access vlan 10"


def test_moving_a_port_into_a_missing_vlan_is_rejected_at_preview(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    monkeypatch.setattr(CiscoIOSXEDriver, "get_vlans", lambda self, parameters: list(_BEFORE))
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.64")

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_access_vlan",
            "target": "GigabitEthernet1",
            "desired_value": "999",
        },
    )

    assert response.status_code == 422, response.text
    assert any("does not exist" in issue for issue in response.json()["error"]["details"]["issues"])
