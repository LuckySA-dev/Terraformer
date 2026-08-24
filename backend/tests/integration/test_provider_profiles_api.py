from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _enable_ai_gateway(settings):
    settings.ai_gateway_enabled = True


def test_create_list_update_delete_provider_profile(authenticated_client: TestClient) -> None:
    create = authenticated_client.post(
        "/api/provider-profiles",
        json={
            "name": "Local Ollama",
            "base_url": "http://localhost:11434/v1",
            "model_id": "llama3.1",
            "api_key": None,
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["name"] == "Local Ollama"
    assert body["has_api_key"] is False
    assert body["supports_streaming"] is False
    profile_id = body["id"]

    listed = authenticated_client.get("/api/provider-profiles")
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [profile_id]

    updated = authenticated_client.patch(
        f"/api/provider-profiles/{profile_id}",
        json={"model_id": "llama3.2"},
    )
    assert updated.status_code == 200
    assert updated.json()["model_id"] == "llama3.2"

    deleted = authenticated_client.delete(f"/api/provider-profiles/{profile_id}")
    assert deleted.status_code == 204
    assert authenticated_client.get("/api/provider-profiles").json() == []


def test_provider_profiles_disabled_by_default(authenticated_client: TestClient, settings) -> None:
    settings.ai_gateway_enabled = False
    response = authenticated_client.get("/api/provider-profiles")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ai_gateway_disabled_by_policy"


def test_create_provider_profile_with_api_key_never_returns_it(
    authenticated_client: TestClient,
) -> None:
    create = authenticated_client.post(
        "/api/provider-profiles",
        json={
            "name": "Cloud",
            "base_url": "https://api.openai.com/v1",
            "model_id": "gpt-4o",
            "api_key": "sk-test-not-a-real-key",
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["has_api_key"] is True
    assert "api_key" not in body
    assert "sk-test-not-a-real-key" not in create.text


class _FakeProviderClient:
    async def probe_capabilities(self, *, base_url: str, api_key: str | None, model_id: str):
        from app.assistant.client import ProviderCapabilities

        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=True)

    async def stream_chat(self, **_kwargs):
        return
        yield  # pragma: no cover -- makes this an async generator; unused here


def test_probe_updates_capability_flags(authenticated_client: TestClient, container) -> None:
    container.ai_provider_client = _FakeProviderClient()
    create = authenticated_client.post(
        "/api/provider-profiles",
        json={"name": "Probed", "base_url": "http://localhost:11434/v1", "model_id": "llama3.1"},
    )
    profile_id = create.json()["id"]

    probed = authenticated_client.post(f"/api/provider-profiles/{profile_id}/probe")
    assert probed.status_code == 200, probed.text
    assert probed.json()["supports_streaming"] is True
    assert probed.json()["supports_tool_calling"] is True
