from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import ApplicationContainer
from app.jobs import tasks


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


def test_preview_refuses_a_description_that_smuggles_a_second_command(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    """The whole Level C promise is that only vetted change types reach a
    device. A newline in the free-form description would ride through render,
    persist newline-joined, and split back into an extra config command at
    apply -- so it has to be refused before any plan exists."""
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.17")

    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_description",
            "target": "GigabitEthernet1",
            "desired_value": "looks-fine\nshutdown",
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "change_validation_failed"
    assert authenticated_client.get(f"/api/change-plans?device_id={device_id}").json() == []


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


def _preview(client: TestClient, device_id: str, target: str = "GigabitEthernet1") -> dict:
    response = client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_description",
            "target": target,
            "desired_value": "new-description",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_successful_apply_reaches_applied_status(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.10")
    plan = _preview(authenticated_client, device_id)

    # FakeTransport is a static command->output lookup table, not a device
    # simulator: it cannot reflect a command it was just sent in a later
    # "show interfaces" read. Patch get_interfaces for the post-check read
    # only, to the state a real device would show after this exact apply --
    # preview() already completed its own get_interfaces call against the
    # unpatched fixture data before this patch is installed.
    from app.drivers import InterfaceFacts
    from app.drivers.cisco_iosxe import CiscoIOSXEDriver

    def applied_interfaces(self, parameters):
        return [
            InterfaceFacts(
                name="GigabitEthernet1", description="new-description", admin_up=True, oper_up=True
            )
        ]

    monkeypatch.setattr(CiscoIOSXEDriver, "get_interfaces", applied_interfaces)

    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    assert queued.status_code == 202, queued.text
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    fetched = authenticated_client.get(f"/api/change-plans/{plan['id']}")
    assert fetched.json()["status"] == "applied"
    assert fetched.json()["applied_at"] is not None


def test_apply_failure_triggers_rollback(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.11")
    plan = _preview(authenticated_client, device_id)

    from app.core.errors import DriverCommandRejectedError
    from app.drivers.cisco_iosxe import CiscoIOSXEDriver

    def failing_apply(self, parameters, commands):
        raise DriverCommandRejectedError()

    monkeypatch.setattr(CiscoIOSXEDriver, "apply_configuration", failing_apply)

    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    fetched = authenticated_client.get(f"/api/change-plans/{plan['id']}")
    assert fetched.json()["status"] == "rolled_back"


def test_apply_and_rollback_both_failing_lands_in_rollback_failed(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.12")
    plan = _preview(authenticated_client, device_id)

    from app.core.errors import DriverCommandRejectedError
    from app.drivers.cisco_iosxe import CiscoIOSXEDriver

    def failing(self, parameters, commands):
        raise DriverCommandRejectedError()

    monkeypatch.setattr(CiscoIOSXEDriver, "apply_configuration", failing)
    monkeypatch.setattr(CiscoIOSXEDriver, "rollback", failing)

    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    fetched = authenticated_client.get(f"/api/change-plans/{plan['id']}")
    assert fetched.json()["status"] == "rollback_failed"


def test_two_applies_to_the_same_device_conflict(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.13")
    plan_a = _preview(authenticated_client, device_id)
    plan_b = _preview(authenticated_client, device_id)

    first = authenticated_client.post(f"/api/change-plans/{plan_a['id']}/apply")
    assert first.status_code == 202, first.text
    second = authenticated_client.post(f"/api/change-plans/{plan_b['id']}/apply")

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "change_plan_device_locked"


def test_applies_to_different_devices_do_not_conflict(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    container.settings.structured_writes_enabled = True
    profile_id = str(credential_profile["id"])
    device_a = _register_cisco(authenticated_client, profile_id, "192.0.2.14")
    device_b = _register_cisco(authenticated_client, profile_id, "192.0.2.15")
    plan_a = _preview(authenticated_client, device_a)
    plan_b = _preview(authenticated_client, device_b)

    first = authenticated_client.post(f"/api/change-plans/{plan_a['id']}/apply")
    second = authenticated_client.post(f"/api/change-plans/{plan_b['id']}/apply")

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text


def test_apply_on_a_non_draft_plan_is_rejected(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch,
) -> None:
    container.settings.structured_writes_enabled = True
    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.16")
    plan = _preview(authenticated_client, device_id)
    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    second_apply = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")

    assert second_apply.status_code == 409
    assert second_apply.json()["error"]["code"] == "change_plan_not_draft"
