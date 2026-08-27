from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _enable_ai_gateway(settings):
    settings.ai_gateway_enabled = True


class _FakeClient:
    """Reports capabilities per model, which is the point of re-probing."""

    def __init__(self) -> None:
        self.probed: list[str] = []

    async def probe_capabilities(self, **kwargs):
        from app.assistant.client import ProviderCapabilities

        model_id = str(kwargs["model_id"])
        self.probed.append(model_id)
        # "basic-model" stands in for a model that cannot call tools, so the
        # switch has to be observable in the session view.
        tools = model_id != "basic-model"
        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=tools)

    async def list_models(self, **_kwargs) -> list[str]:
        return ["test-model", "basic-model"]

    async def stream_chat(self, **_kwargs):
        return
        yield  # pragma: no cover -- async generator, unused here


def _provider_profile(client: TestClient, name: str = "Fake") -> str:
    return client.post(
        "/api/provider-profiles",
        json={"name": name, "base_url": "http://fake/v1"},
    ).json()["id"]


def _new_session(client: TestClient, profile_id: str, model_id: str = "test-model") -> str:
    response = client.post(
        "/api/assistant-sessions",
        json={"provider_profile_id": profile_id, "model_id": model_id},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_switching_model_keeps_the_session_and_its_history(
    authenticated_client: TestClient, container
) -> None:
    container.ai_provider_client = _FakeClient()
    profile_id = _provider_profile(authenticated_client)
    session_id = _new_session(authenticated_client, profile_id)

    switched = authenticated_client.patch(
        f"/api/assistant-sessions/{session_id}",
        json={"provider_profile_id": profile_id, "model_id": "basic-model"},
    )

    assert switched.status_code == 200, switched.text
    # Same conversation, different model -- not a new session, so nothing the
    # operator already said is lost.
    assert switched.json()["id"] == session_id
    assert switched.json()["model_id"] == "basic-model"


def test_capabilities_are_reprobed_against_the_new_model(
    authenticated_client: TestClient, container
) -> None:
    fake = _FakeClient()
    container.ai_provider_client = fake
    profile_id = _provider_profile(authenticated_client)
    session_id = _new_session(authenticated_client, profile_id)

    before = authenticated_client.get("/api/assistant-sessions").json()[0]
    assert before["supports_tool_calling"] is True

    authenticated_client.patch(
        f"/api/assistant-sessions/{session_id}",
        json={"provider_profile_id": profile_id, "model_id": "basic-model"},
    )

    after = authenticated_client.get("/api/assistant-sessions").json()[0]
    # Carrying the previous model's flags forward would advertise tool calling
    # this model does not have.
    assert after["supports_tool_calling"] is False
    assert fake.probed == ["test-model", "basic-model"]


def test_switching_model_does_not_reset_the_auto_apply_allowance(
    authenticated_client: TestClient, container, session_factory
) -> None:
    from uuid import UUID

    from app.repositories.assistant import AssistantSessionRepository

    container.ai_provider_client = _FakeClient()
    profile_id = _provider_profile(authenticated_client)
    session_id = _new_session(authenticated_client, profile_id)

    with session_factory() as db:
        repository = AssistantSessionRepository(db)
        repository.record_auto_apply(repository.get(UUID(session_id)))
        db.commit()

    authenticated_client.patch(
        f"/api/assistant-sessions/{session_id}",
        json={"provider_profile_id": profile_id, "model_id": "basic-model"},
    )

    listed = authenticated_client.get("/api/assistant-sessions").json()[0]
    # Changing model is not a fresh acceptance of risk. Resetting the count
    # here would hand out a new Auto allowance for the price of a dropdown.
    assert listed["auto_apply_count"] == 1


def test_switching_to_an_unreachable_provider_reports_502(
    authenticated_client: TestClient, container
) -> None:
    class _Unreachable(_FakeClient):
        async def probe_capabilities(self, **_kwargs):
            from app.assistant.client import AIProviderConnectionError

            raise AIProviderConnectionError('raw endpoint detail')

    container.ai_provider_client = _FakeClient()
    profile_id = _provider_profile(authenticated_client)
    session_id = _new_session(authenticated_client, profile_id)

    container.ai_provider_client = _Unreachable()
    failed = authenticated_client.patch(
        f"/api/assistant-sessions/{session_id}",
        json={"provider_profile_id": profile_id, "model_id": "test-model"},
    )

    assert failed.status_code == 502, failed.text
    assert 'raw endpoint detail' not in failed.text
    # The session must be left on the model that still works.
    assert authenticated_client.get("/api/assistant-sessions").json()[0]["model_id"] == "test-model"


def _register_cisco(client: TestClient, credential_profile_id: str, address: str, name: str) -> str:
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
        json={"name": name, **connection, "host_key_candidate_id": candidate.json()["id"]},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def test_a_new_chat_defaults_to_every_device(
    authenticated_client: TestClient, container
) -> None:
    container.ai_provider_client = _FakeClient()
    profile_id = _provider_profile(authenticated_client)
    _new_session(authenticated_client, profile_id)

    listed = authenticated_client.get("/api/assistant-sessions").json()[0]
    # Empty is "all devices" -- the same thing every pre-scope session was.
    assert listed["scope_device_ids"] == []


def test_scope_can_name_a_subset_of_devices(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    container.ai_provider_client = _FakeClient()
    credential_id = str(credential_profile["id"])
    sw1 = _register_cisco(authenticated_client, credential_id, "192.0.2.41", "SW1")
    sw2 = _register_cisco(authenticated_client, credential_id, "192.0.2.42", "SW2")
    _register_cisco(authenticated_client, credential_id, "192.0.2.43", "SW3")
    profile_id = _provider_profile(authenticated_client)

    created = authenticated_client.post(
        "/api/assistant-sessions",
        json={
            "provider_profile_id": profile_id,
            "model_id": "test-model",
            "scope_device_ids": [sw1, sw2],
        },
    )

    assert created.status_code == 201, created.text
    assert set(created.json()["scope_device_ids"]) == {sw1, sw2}


def test_scope_and_model_are_edited_independently(
    authenticated_client: TestClient, credential_profile, container
) -> None:
    container.ai_provider_client = _FakeClient()
    device_id = _register_cisco(
        authenticated_client, str(credential_profile["id"]), "192.0.2.44", "SW9"
    )
    profile_id = _provider_profile(authenticated_client)
    session_id = _new_session(authenticated_client, profile_id)

    scoped = authenticated_client.patch(
        f"/api/assistant-sessions/{session_id}",
        json={"scope_device_ids": [device_id]},
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json()["scope_device_ids"] == [device_id]
    # The scope picker must not reset the model the operator chose.
    assert scoped.json()["model_id"] == "test-model"

    switched = authenticated_client.patch(
        f"/api/assistant-sessions/{session_id}",
        json={"provider_profile_id": profile_id, "model_id": "basic-model"},
    )
    assert switched.status_code == 200, switched.text
    # ...and the model picker must not widen the scope back to every device.
    assert switched.json()["scope_device_ids"] == [device_id]
    assert switched.json()["model_id"] == "basic-model"
