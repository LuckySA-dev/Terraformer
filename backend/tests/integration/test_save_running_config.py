from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.drivers.base import DriverCapability


@pytest.fixture(autouse=True)
def _enable_structured_writes(settings):
    settings.structured_writes_enabled = True


def _register_cisco(client: TestClient, credential_profile_id: str, address: str) -> str:
    connection = {
        "management_address": address,
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": credential_profile_id,
        "ssh_compatibility": "modern",
    }
    candidate = client.post("/api/ssh-host-key-candidates", json=connection)
    assert candidate.status_code == 201, candidate.text
    created = client.post(
        "/api/devices",
        json={"name": "SW2", **connection, "host_key_candidate_id": candidate.json()["id"]},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_cisco_declares_the_save_capability(container) -> None:
    from app.models import Vendor

    driver = container.drivers.get(Vendor.CISCO_IOSXE)
    assert driver.capabilities.supports(DriverCapability.SAVE_CONFIG)


def test_saving_reports_success_without_creating_a_change_plan(
    authenticated_client: TestClient, credential_profile, transport_factory
) -> None:
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.51"
    )
    transport_factory.commands["write memory"] = "Building configuration...\r\n[OK]"

    saved = authenticated_client.post(f"/api/change-plans/save-config/{device_id}")

    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] is True
    # It is not a change: nothing to preview, nothing to roll back, so it
    # must not leave a plan behind for someone to re-apply.
    plans = authenticated_client.get(f"/api/change-plans?device_id={device_id}")
    assert plans.json() == []


def test_a_device_that_does_not_confirm_the_save_is_reported_not_assumed(
    authenticated_client: TestClient, credential_profile, transport_factory
) -> None:
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.52"
    )
    # No "[OK]". A save that silently did nothing is the failure that matters:
    # the operator would otherwise believe the config survives a reload.
    transport_factory.commands["write memory"] = "Building configuration..."

    failed = authenticated_client.post(f"/api/change-plans/save-config/{device_id}")

    assert failed.status_code >= 400, failed.text


def test_a_rejected_save_does_not_echo_the_device_reply(
    authenticated_client: TestClient, credential_profile, transport_factory
) -> None:
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.53"
    )
    transport_factory.commands["write memory"] = "% Error opening nvram:startup-config secret"

    failed = authenticated_client.post(f"/api/change-plans/save-config/{device_id}")

    assert failed.status_code >= 400
    # Device replies can quote configuration text, so only the fact of the
    # failure travels back.
    assert "nvram" not in failed.text
    assert "secret" not in failed.text


def test_the_structured_writes_kill_switch_covers_saving(
    authenticated_client: TestClient, credential_profile, settings
) -> None:
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.54"
    )
    settings.structured_writes_enabled = False

    refused = authenticated_client.post(f"/api/change-plans/save-config/{device_id}")

    assert refused.status_code == 403, refused.text
