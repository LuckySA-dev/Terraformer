from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import ApplicationContainer
from tests.fakes import FakeTransportFactory


def candidate(
    client: TestClient,
    profile_id: object,
    *,
    address: str = "edge.example.test",
    port: int = 22,
) -> dict[str, object]:
    response = client.post(
        "/api/ssh-host-key-candidates",
        json={
            "management_address": address,
            "port": port,
            "vendor": "cisco_iosxe",
            "credential_profile_id": profile_id,
            "ssh_compatibility": "modern",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_collects_sanitized_host_key_candidate(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
) -> None:
    response = authenticated_client.post(
        "/api/ssh-host-key-candidates",
        json={
            "management_address": "edge.example.test",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
            "ssh_compatibility": "modern",
        },
    )

    assert response.status_code == 201, response.text
    assert set(response.json()) == {"id", "algorithm", "fingerprint", "expires_at"}
    assert response.json()["fingerprint"] == "SHA256:fixture-host-key"


def test_host_key_candidate_requires_authenticated_app_session(
    client: TestClient,
    credential_profile: dict[str, object],
) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/ssh-host-key-candidates",
        json={
            "management_address": "edge.example.test",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
            "ssh_compatibility": "modern",
        },
    )

    assert response.status_code == 401


def test_manual_add_pins_candidate_before_credentials_and_reuses_pin(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    transport_factory: FakeTransportFactory,
) -> None:
    host_key = candidate(authenticated_client, credential_profile["id"])
    payload = {
        "name": "Edge",
        "management_address": "edge.example.test",
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": credential_profile["id"],
        "ssh_compatibility": "modern",
        "host_key_candidate_id": host_key["id"],
    }

    tested = authenticated_client.post(
        "/api/devices/connection-test",
        json={key: value for key, value in payload.items() if key != "name"},
    )
    assert tested.status_code == 200, tested.text
    created = authenticated_client.post("/api/devices", json=payload)
    assert created.status_code == 201, created.text
    assert transport_factory.parameters[-1].known_hosts == (
        "edge.example.test ssh-ed25519 AAAAfixture\n"
    )

    trust = authenticated_client.get(f"/api/devices/{created.json()['id']}/ssh-host-key")
    assert trust.status_code == 200, trust.text
    assert trust.json()["fingerprint"] == "SHA256:fixture-host-key"
    registered = authenticated_client.post(
        f"/api/devices/{created.json()['id']}/test-connection"
    )
    assert registered.status_code == 200, registered.text
    assert transport_factory.parameters[-1].known_hosts == (
        "edge.example.test ssh-ed25519 AAAAfixture\n"
    )


def test_unconfirmed_or_mismatched_candidate_fails_before_transport(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    transport_factory: FakeTransportFactory,
) -> None:
    unconfirmed = authenticated_client.post(
        "/api/devices/connection-test",
        json={
            "management_address": "edge.example.test",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
        },
    )
    assert unconfirmed.status_code == 502
    assert unconfirmed.json()["error"]["code"] == "device_host_key_unknown"

    host_key = candidate(authenticated_client, credential_profile["id"])
    mismatched = authenticated_client.post(
        "/api/devices/connection-test",
        json={
            "management_address": "edge.example.test",
            "port": 2222,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
            "host_key_candidate_id": host_key["id"],
        },
    )
    assert mismatched.status_code == 409
    assert mismatched.json()["error"]["code"] == "host_key_candidate_mismatch"
    assert transport_factory.parameters == []


def test_candidate_probe_respects_legacy_policy_before_network(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    container.settings.ssh_legacy_enabled = False
    response = authenticated_client.post(
        "/api/ssh-host-key-candidates",
        json={
            "management_address": "edge.example.test",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
            "ssh_compatibility": "cisco_legacy",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "legacy_mode_disabled_by_policy"


def _register(
    client: TestClient,
    profile_id: object,
    *,
    is_lab: bool,
    address: str = "edge.example.test",
) -> dict[str, object]:
    host_key = candidate(client, profile_id, address=address)
    created = client.post(
        "/api/devices",
        json={
            "name": "Edge",
            "management_address": address,
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": profile_id,
            "ssh_compatibility": "modern",
            "is_lab": is_lab,
            "host_key_candidate_id": host_key["id"],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_lab_device_host_key_can_be_repinned_after_the_node_regenerates_it(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
) -> None:
    """GNS3/EVE-NG nodes regenerate their host key on every restart."""
    device = _register(authenticated_client, credential_profile["id"], is_lab=True)
    replacement = candidate(authenticated_client, credential_profile["id"])

    response = authenticated_client.post(
        f"/api/devices/{device['id']}/ssh-host-key/repin",
        json={"host_key_candidate_id": replacement["id"]},
    )

    assert response.status_code == 200, response.text
    trust = authenticated_client.get(f"/api/devices/{device['id']}/ssh-host-key")
    assert trust.json()["fingerprint"] == "SHA256:fixture-host-key"


def test_repin_is_refused_for_devices_not_marked_as_lab(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
) -> None:
    """Real hardware keeps the delete-and-re-register path; a changed key there
    is indistinguishable from a man-in-the-middle."""
    device = _register(authenticated_client, credential_profile["id"], is_lab=False)
    replacement = candidate(authenticated_client, credential_profile["id"])

    response = authenticated_client.post(
        f"/api/devices/{device['id']}/ssh-host-key/repin",
        json={"host_key_candidate_id": replacement["id"]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_capability"
    assert "lab devices" in response.json()["error"]["message"]


def test_telnet_console_requires_a_lab_device(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
) -> None:
    host_key = candidate(authenticated_client, credential_profile["id"])
    response = authenticated_client.post(
        "/api/devices",
        json={
            "name": "Edge",
            "management_address": "edge.example.test",
            "port": 22,
            "vendor": "cisco_iosxe",
            "credential_profile_id": credential_profile["id"],
            "ssh_compatibility": "modern",
            "is_lab": False,
            "console_transport": "telnet",
            "host_key_candidate_id": host_key["id"],
        },
    )

    assert response.status_code == 422, response.text
