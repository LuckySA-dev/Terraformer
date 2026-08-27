from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.repositories.assistant import MAX_AUTO_APPLIES_PER_SESSION


@pytest.fixture(autouse=True)
def _enable_flags(settings):
    settings.ai_gateway_enabled = True
    settings.structured_writes_enabled = True


class _FakeClient:
    async def probe_capabilities(self, **_kwargs):
        from app.assistant.client import ProviderCapabilities

        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=True)

    async def list_models(self, **_kwargs) -> list[str]:
        return ["test-model"]

    async def stream_chat(self, **_kwargs):
        return
        yield  # pragma: no cover -- async generator, unused here


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
        json={
            "name": f"sw-{address}",
            **connection,
            "host_key_candidate_id": candidate.json()["id"],
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _preview(client: TestClient, device_id: str, target: str) -> str:
    response = client.post(
        "/api/change-plans",
        json={
            "device_id": device_id,
            "change_type": "interface_description",
            "target": target,
            "desired_value": "auto-applied",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _auto_session(client: TestClient, container) -> str:
    container.ai_provider_client = _FakeClient()
    profile_id = client.post(
        "/api/provider-profiles", json={"name": "Fake", "base_url": "http://fake/v1"}
    ).json()["id"]
    session_id = client.post(
        "/api/assistant-sessions",
        json={"provider_profile_id": profile_id, "model_id": "test-model"},
    ).json()["id"]
    with client.websocket_connect(
        f"/ws/assistant/{session_id}", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_json({"type": "set_mode", "mode": "auto", "risk_acknowledged": True})
        assert ws.receive_json()["type"] == "mode_changed"
    return str(session_id)


def test_auto_applies_are_counted_against_the_session(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    session_id = _auto_session(authenticated_client, container)
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.41"
    )
    plan_id = _preview(authenticated_client, device_id, "GigabitEthernet1")

    queued = authenticated_client.post(
        f"/api/change-plans/{plan_id}/apply",
        json={"assistant_session_id": session_id},
    )
    assert queued.status_code == 202, queued.text

    listed = authenticated_client.get("/api/assistant-sessions").json()
    session = next(s for s in listed if s["id"] == session_id)
    assert session["auto_apply_count"] == 1


def test_auto_apply_is_refused_once_the_allowance_is_spent(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    session_id = _auto_session(authenticated_client, container)
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.42"
    )

    # Burn the allowance directly: each apply holds a per-device lock, so
    # driving it through the queue would conflict rather than exhaust.
    from uuid import UUID

    from app.models import AssistantSession

    with container.session_factory() as db:
        chat = db.get(AssistantSession, UUID(session_id))
        assert chat is not None
        chat.auto_apply_count = MAX_AUTO_APPLIES_PER_SESSION
        db.commit()

    plan_id = _preview(authenticated_client, device_id, "GigabitEthernet1")
    refused = authenticated_client.post(
        f"/api/change-plans/{plan_id}/apply",
        json={"assistant_session_id": session_id},
    )

    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "auto_apply_limit_reached"


def test_a_human_apply_is_never_rate_limited(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    """Exhausting Auto must not block the operator from applying by hand."""
    session_id = _auto_session(authenticated_client, container)
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.43"
    )

    from uuid import UUID

    from app.models import AssistantSession

    with container.session_factory() as db:
        chat = db.get(AssistantSession, UUID(session_id))
        assert chat is not None
        chat.auto_apply_count = MAX_AUTO_APPLIES_PER_SESSION
        db.commit()

    plan_id = _preview(authenticated_client, device_id, "GigabitEthernet1")
    # No assistant_session_id -- this is a human pressing Apply.
    queued = authenticated_client.post(f"/api/change-plans/{plan_id}/apply")

    assert queued.status_code == 202, queued.text


def test_confirm_mode_applies_are_not_counted(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    """Only Auto spends the allowance, even if the client sends its session."""
    container.ai_provider_client = _FakeClient()
    profile_id = authenticated_client.post(
        "/api/provider-profiles", json={"name": "Fake", "base_url": "http://fake/v1"}
    ).json()["id"]
    session_id = authenticated_client.post(
        "/api/assistant-sessions",
        json={"provider_profile_id": profile_id, "model_id": "test-model"},
    ).json()["id"]
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.44"
    )
    plan_id = _preview(authenticated_client, device_id, "GigabitEthernet1")

    queued = authenticated_client.post(
        f"/api/change-plans/{plan_id}/apply",
        json={"assistant_session_id": session_id},
    )
    assert queued.status_code == 202, queued.text

    listed = authenticated_client.get("/api/assistant-sessions").json()
    session = next(s for s in listed if s["id"] == session_id)
    assert session["auto_apply_count"] == 0
