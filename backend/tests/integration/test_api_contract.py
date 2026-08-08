"""Frontend/backend request-shape contract.

The frontend tests mock `fetch`, so they never exercise a real request schema.
That let commit 9fc21fc ship a frontend that sends `very_old_risk_acknowledged`
to schemas built with `extra="forbid"`, which rejected every add-device attempt
with a 422 while every automated test stayed green.

These tests post the exact payloads `frontend/src/api/network.ts` builds, so a
field added on one side without the other fails here immediately.

Keep `_DEVICE_INPUT_FIELDS` in sync with the `DeviceInput` interface in
`frontend/src/types/api.ts`.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

# Mirrors DeviceInput in frontend/src/types/api.ts.
_DEVICE_INPUT_FIELDS = (
    "name",
    "management_address",
    "port",
    "vendor",
    "credential_profile_id",
    "ssh_compatibility",
    "group1_risk_acknowledged",
    "very_old_risk_acknowledged",
    "host_key_candidate_id",
)

# Fields network.ts strips before calling the connection endpoints.
_CONNECTION_ONLY = tuple(field for field in _DEVICE_INPUT_FIELDS if field != "name")
_CANDIDATE_ONLY = tuple(
    field for field in _CONNECTION_ONLY if field != "host_key_candidate_id"
)


def _device_input(profile_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "edge-rtr-contract",
        "management_address": "192.0.2.77",
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": profile_id,
        "ssh_compatibility": "modern",
        "group1_risk_acknowledged": False,
        "very_old_risk_acknowledged": False,
    }
    payload.update(overrides)
    return payload


def _subset(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key in fields}


def test_device_input_covers_every_field_the_frontend_sends() -> None:
    """Guards the fixture itself against silently drifting from the UI type."""
    assert set(_device_input("00000000-0000-0000-0000-000000000000")) | {
        "host_key_candidate_id"
    } == set(_DEVICE_INPUT_FIELDS)


def test_add_device_flow_accepts_the_exact_frontend_payloads(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
) -> None:
    profile_id = str(credential_profile["id"])
    payload = _device_input(profile_id)

    candidate = authenticated_client.post(
        "/api/ssh-host-key-candidates", json=_subset(payload, _CANDIDATE_ONLY)
    )
    assert candidate.status_code == 201, candidate.text

    payload["host_key_candidate_id"] = candidate.json()["id"]

    tested = authenticated_client.post(
        "/api/devices/connection-test", json=_subset(payload, _CONNECTION_ONLY)
    )
    assert tested.status_code == 200, tested.text

    created = authenticated_client.post("/api/devices", json=payload)
    assert created.status_code == 201, created.text


@pytest.mark.parametrize(
    ("method", "path", "fields"),
    [
        ("post", "/api/ssh-host-key-candidates", _CANDIDATE_ONLY),
        ("post", "/api/devices/connection-test", _CONNECTION_ONLY),
        ("post", "/api/devices", _DEVICE_INPUT_FIELDS),
    ],
)
def test_connection_endpoints_never_reject_a_frontend_field_as_unknown(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    method: str,
    path: str,
    fields: tuple[str, ...],
) -> None:
    """A 422 here means the frontend sends a field the schema forbids.

    405 would mean the route or verb moved. Both are the failure modes reported
    against the add-device flow.
    """
    payload = _subset(
        _device_input(str(credential_profile["id"]), host_key_candidate_id=None), fields
    )
    response = getattr(authenticated_client, method)(path, json=payload)

    assert response.status_code != 405, f"{method.upper()} {path} is not routed"
    if response.status_code == 422:
        pytest.fail(f"{path} rejected a frontend field: {response.text}")
