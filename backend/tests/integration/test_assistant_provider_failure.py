from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.assistant.client import AIProviderConnectionError, ProviderCapabilities


@pytest.fixture(autouse=True)
def _enable_ai_gateway(settings):
    settings.ai_gateway_enabled = True


class _FailingClient:
    """Reaches probe (so the session can be created) then fails on chat."""

    def __init__(self, message: str) -> None:
        self._message = message

    async def probe_capabilities(self, **_kwargs):
        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=False)

    async def list_models(self, **_kwargs) -> list[str]:
        return ["test-model"]

    async def stream_chat(self, **_kwargs):
        raise AIProviderConnectionError(self._message)
        yield  # pragma: no cover -- makes this an async generator


def _session(client: TestClient) -> str:
    profile_id = client.post(
        "/api/provider-profiles", json={"name": "Fake", "base_url": "http://fake/v1"}
    ).json()["id"]
    return str(
        client.post(
            "/api/assistant-sessions",
            json={"provider_profile_id": profile_id, "model_id": "test-model"},
        ).json()["id"]
    )


def test_a_provider_failure_is_reported_instead_of_killing_the_chat(
    authenticated_client: TestClient, container
) -> None:
    container.ai_provider_client = _FailingClient("401 Unauthorized")
    session_id = _session(authenticated_client)

    with authenticated_client.websocket_connect(
        f"/ws/assistant/{session_id}", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_json({"type": "user_message", "content": "hello"})
        frame = ws.receive_json()

        assert frame["type"] == "error"
        assert frame["code"] == "provider_unreachable"
        assert "401 Unauthorized" in frame["message"]

        # The socket must still be usable -- the operator should be able to
        # fix the key and carry on rather than reload the page.
        ws.send_json({"type": "set_mode", "mode": "confirm", "risk_acknowledged": False})
        assert ws.receive_json()["type"] == "mode_changed"


def test_a_provider_failure_never_echoes_the_api_key_back(
    authenticated_client: TestClient, container
) -> None:
    leaked = "sk-ant-api03-THISISNOTAREALKEY1234567890"
    container.ai_provider_client = _FailingClient(
        f"401 Unauthorized: invalid x-api-key {leaked}"
    )
    session_id = _session(authenticated_client)

    with authenticated_client.websocket_connect(
        f"/ws/assistant/{session_id}", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_json({"type": "user_message", "content": "hello"})
        frame = ws.receive_json()

    assert frame["type"] == "error"
    assert leaked not in frame["message"]
    assert "[redacted]" in frame["message"]
