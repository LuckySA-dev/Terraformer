from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _enable_ai_gateway(settings):
    settings.ai_gateway_enabled = True


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


def _provider_profile(client: TestClient) -> str:
    return client.post(
        "/api/provider-profiles",
        json={"name": "Fake", "base_url": "http://fake/v1"},
    ).json()["id"]


def _new_session(client: TestClient, profile_id: str, device_id: str | None) -> str:
    body: dict[str, object] = {"provider_profile_id": profile_id, "model_id": "test-model"}
    if device_id is not None:
        body["device_id"] = device_id
    response = client.post("/api/assistant-sessions", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_a_device_chat_is_not_listed_for_another_device(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    container.ai_provider_client = _FakeClient()
    credential_id = str(credential_profile["id"])
    first = _register_cisco(authenticated_client, credential_id, "192.0.2.31")
    second = _register_cisco(authenticated_client, credential_id, "192.0.2.32")
    profile_id = _provider_profile(authenticated_client)

    first_session = _new_session(authenticated_client, profile_id, first)
    _new_session(authenticated_client, profile_id, second)

    listed = authenticated_client.get(f"/api/assistant-sessions?scope=device&device_id={first}")
    assert listed.status_code == 200, listed.text
    assert [s["id"] for s in listed.json()] == [first_session]


def test_workspace_scope_excludes_every_device_chat(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    container.ai_provider_client = _FakeClient()
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.33"
    )
    profile_id = _provider_profile(authenticated_client)

    workspace_session = _new_session(authenticated_client, profile_id, None)
    _new_session(authenticated_client, profile_id, device_id)

    listed = authenticated_client.get("/api/assistant-sessions?scope=workspace")
    assert listed.status_code == 200, listed.text
    assert [s["id"] for s in listed.json()] == [workspace_session]


def test_a_device_chat_reports_the_device_it_belongs_to(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    container.ai_provider_client = _FakeClient()
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.34"
    )
    profile_id = _provider_profile(authenticated_client)

    session_id = _new_session(authenticated_client, profile_id, device_id)

    listed = authenticated_client.get("/api/assistant-sessions").json()
    session = next(s for s in listed if s["id"] == session_id)
    assert session["device_id"] == device_id


def test_deleting_a_device_takes_its_chats_with_it(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    container.ai_provider_client = _FakeClient()
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.35"
    )
    profile_id = _provider_profile(authenticated_client)
    session_id = _new_session(authenticated_client, profile_id, device_id)

    deleted = authenticated_client.delete(f"/api/devices/{device_id}")
    assert deleted.status_code == 204, deleted.text

    remaining = [s["id"] for s in authenticated_client.get("/api/assistant-sessions").json()]
    assert session_id not in remaining


def test_a_device_scoped_chat_tells_the_model_which_device_it_is(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    """The operator should not have to paste a UUID into a device's own chat."""
    from app.assistant.client import ChatChunk

    captured: dict[str, object] = {}

    class _CapturingClient(_FakeClient):
        async def stream_chat(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            yield ChatChunk(type="token", content="ok")

    container.ai_provider_client = _CapturingClient()
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.36"
    )
    profile_id = _provider_profile(authenticated_client)
    session_id = _new_session(authenticated_client, profile_id, device_id)

    with authenticated_client.websocket_connect(
        f"/ws/assistant/{session_id}", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_json({"type": "user_message", "content": "what is this?"})
        while ws.receive_json()["type"] != "done":
            pass

    messages = captured["messages"]
    assert isinstance(messages, list)
    system = messages[0]
    assert device_id in system.content
    assert "sw-192.0.2.36" in system.content


def test_a_workspace_chat_names_no_device(
    authenticated_client: TestClient, container
) -> None:
    from app.assistant.client import ChatChunk

    captured: dict[str, object] = {}

    class _CapturingClient(_FakeClient):
        async def stream_chat(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            yield ChatChunk(type="token", content="ok")

    container.ai_provider_client = _CapturingClient()
    profile_id = _provider_profile(authenticated_client)
    session_id = _new_session(authenticated_client, profile_id, None)

    with authenticated_client.websocket_connect(
        f"/ws/assistant/{session_id}", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_json({"type": "user_message", "content": "hello"})
        while ws.receive_json()["type"] != "done":
            pass

    messages = captured["messages"]
    assert isinstance(messages, list)
    assert "This conversation is about the device" not in messages[0].content
