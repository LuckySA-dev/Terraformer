"""Regressions found while debugging the config window's backend path.

Each test here failed before the fix it names. They go through the API rather
than the driver so they cover the order the service actually does things in,
which is where three of the four bugs lived.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.container import ApplicationContainer
from app.drivers.base import InterfaceFacts, VlanFacts
from app.drivers.cisco_iosxe import CiscoIOSXEDriver
from app.jobs import tasks

_INTERFACES = [
    InterfaceFacts(
        name="GigabitEthernet1",
        description="old-uplink",
        admin_up=True,
        oper_up=False,
    )
]
_VLANS = [VlanFacts(vlan_id=10, name="USERS", status="active", ports=("GigabitEthernet1",))]


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


@pytest.fixture
def cisco(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
    monkeypatch: pytest.MonkeyPatch,
):
    container.settings.structured_writes_enabled = True
    monkeypatch.setattr(CiscoIOSXEDriver, "get_interfaces", lambda self, parameters: _INTERFACES)
    monkeypatch.setattr(CiscoIOSXEDriver, "get_vlans", lambda self, parameters: list(_VLANS))
    # The fake transport is a static command lookup, so the reads a change type
    # needs are supplied directly rather than through invented device output.
    monkeypatch.setattr(CiscoIOSXEDriver, "get_switchports", lambda self, parameters: [])
    monkeypatch.setattr(CiscoIOSXEDriver, "get_static_routes", lambda self, parameters: [])

    def _register(address: str) -> str:
        return _register_cisco(authenticated_client, str(credential_profile["id"]), address)

    return _register


# --- validation ran after rendering ----------------------------------------


@pytest.mark.parametrize(
    ("change_type", "target", "desired_value"),
    [
        ("vlan_name", "abc", "STAFF"),
        ("interface_access_vlan", "GigabitEthernet1", "not-a-number"),
        ("static_route", "not-a-prefix", "192.0.2.1"),
    ],
)
def test_a_malformed_target_is_a_rejection_not_a_server_error(
    authenticated_client: TestClient,
    cisco,
    change_type: str,
    target: str,
    desired_value: str,
) -> None:
    # preview() rendered before it validated, and renderers parse the target as
    # an integer or a prefix because they are entitled to assume a validated
    # step. So a typo came back as a bare ValueError -- a 500 with no issues
    # list -- instead of the 422 saying what was wrong with it.
    device_id = cisco("192.0.2.70")
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": change_type,
            "target": target,
            "desired_value": desired_value,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["issues"]


# --- the log sanitizer rewrote the commands --------------------------------


def test_a_description_is_configured_as_typed_not_as_the_log_sanitizer_rewrote_it(
    authenticated_client: TestClient,
    cisco,
) -> None:
    # The stored commands went through sanitize_text, which rewrites the token
    # after "password", "secret", "token", "community" or "api key". So this
    # description was stored -- and would have been sent to the device -- as
    # "link to community [REDACTED]", and the rollback carried the same damage.
    device_id = cisco("192.0.2.71")
    response = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_description",
            "target": "GigabitEthernet1",
            "desired_value": "link to community switch",
        },
    )
    assert response.status_code == 201, response.text
    step = response.json()["steps"][0]
    assert "REDACTED" not in step["rendered_commands"]
    assert step["rendered_commands"] == (
        "interface GigabitEthernet1\ndescription link to community switch"
    )
    # The preview pane, the commands sent, and the rollback must be one string.
    assert step["desired_value"] == "link to community switch"
    assert step["inverse_commands"] == "interface GigabitEthernet1\ndescription old-uplink"


# --- the outcome the operator reads ----------------------------------------


def test_a_post_check_failure_says_so_rather_than_internal_error(
    authenticated_client: TestClient,
    container: ApplicationContainer,
    cisco,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The failure was raised as a bare AppError, whose code is "internal_error".
    # The config window shows failure_code verbatim, so the one outcome an
    # operator most needs to understand read like a crash.
    device_id = cisco("192.0.2.72")
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
    assert queued.status_code == 202, queued.text
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    # get_vlans still reports USERS, so the change did not take.
    settled = authenticated_client.get(f"/api/change-plans/{plan['id']}").json()
    assert settled["status"] in ("rolled_back", "rollback_failed")
    assert settled["failure_code"] == "post_check_failed"


def test_an_unexpected_fault_ends_the_plan_instead_of_leaving_it_applying(
    authenticated_client: TestClient,
    container: ApplicationContainer,
    cisco,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # apply() caught only AppError. Anything else -- a parser raising
    # ValueError, a bug in a driver -- escaped with the plan still marked
    # APPLYING. It could then never be applied or rolled back again, and the
    # config window polls that status forever.
    device_id = cisco("192.0.2.73")
    plan = authenticated_client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "vlan_name",
            "target": "10",
            "desired_value": "STAFF",
        },
    ).json()

    def _explode(self, parameters, commands):
        raise ValueError("a driver bug that is not an AppError")

    monkeypatch.setattr(CiscoIOSXEDriver, "apply_configuration", _explode)
    queued = authenticated_client.post(f"/api/change-plans/{plan['id']}/apply")
    monkeypatch.setattr(tasks, "get_default_container", lambda: container)
    tasks.execute_job(queued.json()["id"])

    settled = authenticated_client.get(f"/api/change-plans/{plan['id']}").json()
    assert settled["status"] != "applying"
    assert settled["status"] in ("rolled_back", "rollback_failed", "failed")
    assert settled["failure_code"] == "change_apply_failed"
