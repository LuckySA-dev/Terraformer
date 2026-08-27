from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.container import ApplicationContainer


@pytest.fixture(autouse=True)
def _enable_flags(settings):
    settings.ai_gateway_enabled = True
    settings.structured_writes_enabled = True


def _register_cisco(client: TestClient, profile_id: str, address: str) -> str:
    connection = {
        "management_address": address,
        "port": 22,
        "vendor": "cisco_iosxe",
        "credential_profile_id": profile_id,
        "ssh_compatibility": "modern",
    }
    candidate = client.post(
        "/api/ssh-host-key-candidates",
        json={key: value for key, value in connection.items() if key != "name"},
    )
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


def test_ai_generated_change_plan_is_tagged_and_applies_through_the_normal_pipeline(
    authenticated_client: TestClient,
    credential_profile: dict[str, object],
    container: ApplicationContainer,
) -> None:
    from app.assistant.client import ChatChunk, ProviderCapabilities, ToolCallRequest

    class _FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def probe_capabilities(self, **_kwargs):
            return ProviderCapabilities(supports_streaming=True, supports_tool_calling=True)

        async def stream_chat(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                yield ChatChunk(
                    type="tool_call",
                    tool_call=ToolCallRequest(
                        id="1",
                        name="propose_change_plan",
                        arguments={
                            "device_id": device_id,
                            "change_type": "interface_description",
                            "target": "GigabitEthernet1",
                            "desired_value": "ai-drafted uplink",
                        },
                    ),
                )
            else:
                yield ChatChunk(type="token", content="Proposed the change above.")

    device_id = _register_cisco(authenticated_client, str(credential_profile["id"]), "192.0.2.20")
    container.ai_provider_client = _FakeClient()

    profile_id = authenticated_client.post(
        "/api/provider-profiles",
        json={"name": "Fake", "base_url": "http://fake/v1"},
    ).json()["id"]
    session_id = authenticated_client.post(
        "/api/assistant-sessions",
        json={"provider_profile_id": profile_id, "model_id": "test-model"},
    ).json()["id"]

    with authenticated_client.websocket_connect(
        f"/ws/assistant/{session_id}", headers={"origin": "http://testserver"}
    ) as ws:
        ws.send_json({"type": "user_message", "content": "set the uplink description"})
        frames = []
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame["type"] == "done":
                break

    proposed = next(f for f in frames if f["type"] == "change_plan_proposed")
    plan_id = proposed["payload"]["plan_id"]

    plan_response = authenticated_client.get(f"/api/change-plans?device_id={device_id}")
    assert plan_response.status_code == 200, plan_response.text
    plan = next(p for p in plan_response.json() if p["id"] == plan_id)
    assert plan["source"] == "ai_generated"
    assert plan["status"] == "draft"
