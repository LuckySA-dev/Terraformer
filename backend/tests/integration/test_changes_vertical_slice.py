from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import ApplicationContainer


def _register_cisco(client: TestClient, profile_id: str, address: str) -> str:
    connection = {
        "management_address": address,
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": profile_id,
        "ssh_compatibility": "modern",
    }
    candidate = client.post(
        "/api/ssh-host-key-candidates",
        json={key: value for key, value in connection.items() if key != "name"},
    )
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


def test_preview_returns_diff_risk_and_rendered_commands(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.10")

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_description",
            "target": "GigabitEthernet1",
            "desired_value": "uplink-to-lab-core",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["safety_level"] == "C"
    assert body["risk"] in ("low", "high")
    assert len(body["steps"]) == 1
    assert "description uplink-to-lab-core" in body["steps"][0]["rendered_commands"]


def test_preview_rejects_non_cisco_vendor(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = True
    profile_id = str(credential_profile["id"])
    connection = {
        "management_address": "192.0.2.20",
        "port": 22,
        "vendor": "generic",
        "credential_profile_id": profile_id,
        "ssh_compatibility": "modern",
    }
    candidate = authenticated_client.post("/api/ssh-host-key-candidates", json=connection)
    created = authenticated_client.post(
        "/api/devices",
        json={"name": "generic-box", **connection, "host_key_candidate_id": candidate.json()["id"]},
    )
    device_id = created.json()["id"]

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_description",
            "target": "eth0",
            "desired_value": "x",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "change_vendor_unsupported"


def test_every_endpoint_fails_closed_when_structured_writes_disabled(
    authenticated_client: TestClient,
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = False

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": "00000000-0000-0000-0000-000000000000",
            "change_type": "interface_description",
            "target": "GigabitEthernet1",
            "desired_value": "x",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "structured_writes_disabled_by_policy"
