from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _enable_ai_gateway(settings):
    settings.ai_gateway_enabled = True


def test_assistant_chat_streams_a_reply(authenticated_client: TestClient, container) -> None:
    from app.assistant.client import ChatChunk

    class _FakeClient:
        async def probe_capabilities(self, **_kwargs):
            raise AssertionError("not used")

        async def stream_chat(self, **_kwargs):
            yield ChatChunk(type="token", content="Hello")
            yield ChatChunk(type="token", content=" there")

    container.ai_provider_client = _FakeClient()

    profile_id = authenticated_client.post(
        "/api/provider-profiles",
        json={"name": "Local", "base_url": "http://localhost:11434/v1", "model_id": "llama3.1"},
    ).json()["id"]
    chat_session_id = authenticated_client.post(
        "/api/assistant-sessions", json={"provider_profile_id": profile_id}
    ).json()["id"]

    with authenticated_client.websocket_connect(
        f"/ws/assistant/{chat_session_id}", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_json({"type": "user_message", "content": "hi"})
        frames = [ws.receive_json() for _ in range(3)]

    assert [f["content"] for f in frames if f["type"] == "token"] == ["Hello", " there"]
    assert frames[-1]["type"] == "done"


def test_assistant_websocket_rejects_missing_origin(
    authenticated_client: TestClient, container
) -> None:
    from app.assistant.client import ChatChunk

    class _FakeClient:
        async def probe_capabilities(self, **_kwargs):
            raise AssertionError("not used")

        async def stream_chat(self, **_kwargs):
            yield ChatChunk(type="done")

    container.ai_provider_client = _FakeClient()

    profile_id = authenticated_client.post(
        "/api/provider-profiles",
        json={"name": "Local", "base_url": "http://localhost:11434/v1", "model_id": "llama3.1"},
    ).json()["id"]
    chat_session_id = authenticated_client.post(
        "/api/assistant-sessions", json={"provider_profile_id": profile_id}
    ).json()["id"]

    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with authenticated_client.websocket_connect(
            f"/ws/assistant/{chat_session_id}", headers={"origin": "http://evil.example"}
        ):
            pass
