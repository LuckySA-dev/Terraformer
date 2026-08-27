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
            "api_key": None,
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["name"] == "Local Ollama"
    assert body["has_api_key"] is False
    profile_id = body["id"]

    listed = authenticated_client.get("/api/provider-profiles")
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [profile_id]

    updated = authenticated_client.patch(
        f"/api/provider-profiles/{profile_id}",
        json={"base_url": "http://localhost:11434/v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["base_url"] == "http://localhost:11434/v2"

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

    async def list_models(self, *, base_url: str, api_key: str | None) -> list[str]:
        return ["llama3.1", "llama3.2"]

    async def stream_chat(self, **_kwargs):
        return
        yield  # pragma: no cover -- makes this an async generator; unused here


def test_get_profile_models_uses_the_saved_profile_key(
    authenticated_client: TestClient, container
) -> None:
    container.ai_provider_client = _FakeProviderClient()
    create = authenticated_client.post(
        "/api/provider-profiles",
        json={"name": "Saved", "base_url": "http://localhost:11434/v1"},
    )
    profile_id = create.json()["id"]

    response = authenticated_client.get(f"/api/provider-profiles/{profile_id}/models")
    assert response.status_code == 200, response.text
    assert response.json()["models"] == ["llama3.1", "llama3.2"]


def test_profile_defaults_to_the_openai_compatible_wire_format(
    authenticated_client: TestClient,
) -> None:
    created = authenticated_client.post(
        "/api/provider-profiles",
        json={"name": "Default", "base_url": "http://localhost:11434/v1"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["provider_type"] == "openai_compatible"


def test_an_anthropic_profile_is_served_by_the_anthropic_adapter(
    authenticated_client: TestClient, container
) -> None:
    # Distinct fakes: the assertion is that the routing picked the Anthropic
    # one, which a shared fake could not tell apart.
    class _AnthropicFake(_FakeProviderClient):
        async def list_models(self, *, base_url: str, api_key: str | None) -> list[str]:
            return ["claude-opus-5"]

    container.ai_provider_client = _FakeProviderClient()
    container.anthropic_provider_client = _AnthropicFake()

    profile_id = authenticated_client.post(
        "/api/provider-profiles",
        json={
            "name": "Claude",
            "provider_type": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key": "sk-ant-not-a-real-key",
        },
    ).json()["id"]

    response = authenticated_client.get(f"/api/provider-profiles/{profile_id}/models")

    assert response.status_code == 200, response.text
    assert response.json()["models"] == ["claude-opus-5"]


def test_list_models_returns_the_providers_model_ids(
    authenticated_client: TestClient, container
) -> None:
    container.ai_provider_client = _FakeProviderClient()

    response = authenticated_client.post(
        "/api/provider-profiles/list-models",
        json={"base_url": "http://localhost:11434/v1", "api_key": None},
    )

    assert response.status_code == 200, response.text
    assert response.json()["models"] == ["llama3.1", "llama3.2"]


def test_list_models_never_persists_anything(authenticated_client: TestClient, container) -> None:
    container.ai_provider_client = _FakeProviderClient()

    authenticated_client.post(
        "/api/provider-profiles/list-models",
        json={"base_url": "http://localhost:11434/v1", "api_key": "sk-throwaway"},
    )

    assert authenticated_client.get("/api/provider-profiles").json() == []
