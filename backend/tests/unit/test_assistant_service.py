from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from app.assistant.client import ChatChunk, ToolCallRequest
from app.assistant.service import AssistantChatService
from app.assistant.tools import ReadOnlyToolError, ToolResult
from app.models import AssistantSessionMode

pytestmark = pytest.mark.anyio


class _FakeSessions:
    def __init__(self, chat_session):
        self._chat_session = chat_session

    def get(self, session_id, *, for_update: bool = False):
        return self._chat_session

    def set_mode(self, chat_session, mode):
        chat_session.mode = mode


class _FakeMessages:
    def __init__(self):
        self.added: list[dict[str, object]] = []

    def add(self, *, session_id, role, content, tool_calls=None, tool_results=None):
        self.added.append({"role": role, "content": content})

    def list_for_session(self, session_id):
        return []


class _FakeProfiles:
    def __init__(self, profile):
        self._profile = profile

    def get(self, profile_id):
        return self._profile


class _FakeVault:
    def decrypt(self, profile):
        from app.services.provider_profiles import ProviderKeyMaterial

        return ProviderKeyMaterial(api_key=None)


class _FakeProviderClient:
    def __init__(self, rounds: list[list[ChatChunk]]):
        self._rounds = rounds
        self.calls = 0

    async def probe_capabilities(self, **_kwargs):
        raise AssertionError("not used")

    async def stream_chat(self, **_kwargs) -> AsyncIterator[ChatChunk]:
        chunks = self._rounds[self.calls]
        self.calls += 1
        for chunk in chunks:
            yield chunk


class _FakeToolDispatcher:
    def dispatch(self, name, arguments):
        if name == "boom":
            raise ReadOnlyToolError("no such device")
        return ToolResult(name=name, payload={"facts": {"hostname": "r1"}})


class _FakeDbSession:
    def commit(self) -> None:
        pass


class _Profile:
    id = uuid4()
    base_url = "http://fake/v1"
    model_id = "test-model"
    supports_tool_calling = True


class _Session:
    id = uuid4()
    provider_profile_id = uuid4()
    mode = AssistantSessionMode.CONFIRM


def _service(provider: _FakeProviderClient, *, changes=None) -> AssistantChatService:
    kwargs: dict[str, object] = {}
    if changes is not None:
        kwargs["changes"] = changes
    return AssistantChatService(
        session=_FakeDbSession(),  # type: ignore[arg-type]
        provider_client=provider,
        sessions=_FakeSessions(_Session()),
        messages=_FakeMessages(),
        profiles=_FakeProfiles(_Profile()),
        vault=_FakeVault(),  # type: ignore[arg-type]
        tools=_FakeToolDispatcher(),  # type: ignore[arg-type]
        **kwargs,
    )


async def test_handle_user_message_streams_tokens_then_done() -> None:
    provider = _FakeProviderClient(
        [[ChatChunk(type="token", content="Hi"), ChatChunk(type="token", content="!")]]
    )
    service = _service(provider)

    events = [e async for e in service.handle_user_message(uuid4(), "hello")]

    assert [e.content for e in events if e.type == "token"] == ["Hi", "!"]
    assert events[-1].type == "done"


async def test_handle_user_message_dispatches_a_tool_call_then_continues() -> None:
    provider = _FakeProviderClient(
        [
            [
                ChatChunk(
                    type="tool_call",
                    tool_call=ToolCallRequest(
                        id="1", name="get_device_facts", arguments={"device_id": "x"}
                    ),
                )
            ],
            [ChatChunk(type="token", content="Done")],
        ]
    )
    service = _service(provider)

    events = [e async for e in service.handle_user_message(uuid4(), "check the device")]

    tool_events = [e for e in events if e.type == "tool_result"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_payload == {"facts": {"hostname": "r1"}}
    assert provider.calls == 2
    assert events[-1].type == "done"


async def test_handle_user_message_reports_tool_errors_without_crashing() -> None:
    provider = _FakeProviderClient(
        [
            [
                ChatChunk(
                    type="tool_call",
                    tool_call=ToolCallRequest(id="1", name="boom", arguments={"device_id": "x"}),
                )
            ],
            [ChatChunk(type="token", content="Sorry")],
        ]
    )
    service = _service(provider)

    events = [e async for e in service.handle_user_message(uuid4(), "check a bad device")]

    tool_events = [e for e in events if e.type == "tool_result"]
    assert tool_events[0].tool_payload == {"error": "no such device"}
