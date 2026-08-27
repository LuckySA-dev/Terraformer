from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from app.assistant.client import ChatChunk, ToolCallRequest
from app.assistant.service import AssistantChatService
from app.assistant.tools import ReadOnlyToolError, ToolResult
from app.models import AssistantSessionMode, ProviderType

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
    provider_type = ProviderType.OPENAI_COMPATIBLE


class _Session:
    id = uuid4()
    provider_profile_id = uuid4()
    device_id = None
    model_id = "test-model"
    supports_tool_calling = True
    context_limit_override = None
    mode = AssistantSessionMode.CONFIRM


def _service(provider: _FakeProviderClient, *, changes=None) -> AssistantChatService:
    kwargs: dict[str, object] = {}
    if changes is not None:
        kwargs["changes"] = changes
    return AssistantChatService(
        session=_FakeDbSession(),  # type: ignore[arg-type]
        provider_client_for=lambda _provider_type: provider,
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


class _FakeChanges:
    def __init__(self, plan=None, error=None):
        self._plan = plan
        self._error = error

    def preview(self, **_kwargs):
        if self._error is not None:
            raise self._error
        return self._plan


def _fake_plan():
    from app.models import ChangePlanSource, ChangePlanStatus, ChangeRisk, SafetyLevel

    class _Step:
        target = "GigabitEthernet0/1"
        desired_value = "ai-drafted uplink"
        rendered_commands = "interface GigabitEthernet0/1\n description ai-drafted uplink"

    class _Plan:
        id = uuid4()
        status = ChangePlanStatus.DRAFT
        risk = ChangeRisk.LOW
        safety_level = SafetyLevel.BEST_EFFORT
        source = ChangePlanSource.AI_GENERATED
        steps = (_Step(),)

    return _Plan()


async def test_propose_change_plan_tool_creates_a_draft_plan() -> None:
    provider = _FakeProviderClient(
        [
            [
                ChatChunk(
                    type="tool_call",
                    tool_call=ToolCallRequest(
                        id="1",
                        name="propose_change_plan",
                        arguments={
                            "device_id": str(uuid4()),
                            "change_type": "interface_description",
                            "target": "GigabitEthernet0/1",
                            "desired_value": "ai-drafted uplink",
                        },
                    ),
                )
            ],
            [ChatChunk(type="token", content="Proposed.")],
        ]
    )
    service = _service(provider, changes=_FakeChanges(plan=_fake_plan()))

    events = [e async for e in service.handle_user_message(uuid4(), "set the uplink description")]

    proposed = [e for e in events if e.type == "change_plan_proposed"]
    assert len(proposed) == 1
    assert proposed[0].tool_payload["status"] == "draft"
    assert proposed[0].tool_payload["steps"][0]["desired_value"] == "ai-drafted uplink"


async def test_propose_change_plan_surfaces_validation_failure_without_crashing() -> None:
    from app.core.errors import ChangeValidationError

    provider = _FakeProviderClient(
        [
            [
                ChatChunk(
                    type="tool_call",
                    tool_call=ToolCallRequest(
                        id="1",
                        name="propose_change_plan",
                        arguments={
                            "device_id": str(uuid4()),
                            "change_type": "interface_description",
                            "target": "GigabitEthernet0/1",
                            "desired_value": "bad\nvalue",
                        },
                    ),
                )
            ],
            [ChatChunk(type="token", content="Sorry, that failed validation.")],
        ]
    )
    error = ChangeValidationError(details={"issues": ["desired_value must be printable"]})
    service = _service(provider, changes=_FakeChanges(error=error))

    events = [e async for e in service.handle_user_message(uuid4(), "set a bad description")]

    tool_events = [e for e in events if e.type == "tool_result"]
    assert "issues" in tool_events[0].tool_payload


class _RecordingProviderClient:
    def __init__(self):
        self.received_tools = None

    async def probe_capabilities(self, **_kwargs):
        raise AssertionError("not used")

    async def stream_chat(self, *, tools, **_kwargs) -> AsyncIterator[ChatChunk]:
        self.received_tools = tools
        yield ChatChunk(type="token", content="ok")


async def test_propose_change_plan_tool_is_excluded_when_structured_writes_off() -> None:
    provider = _RecordingProviderClient()
    service = _service(provider)  # no `changes` -> structured writes off

    async for _event in service.handle_user_message(uuid4(), "hello"):
        pass

    tool_names = [t.name for t in (provider.received_tools or [])]
    assert "propose_change_plan" not in tool_names


async def test_propose_change_plan_tool_is_offered_when_structured_writes_on() -> None:
    provider = _RecordingProviderClient()
    service = _service(provider, changes=_FakeChanges(plan=_fake_plan()))

    async for _event in service.handle_user_message(uuid4(), "hello"):
        pass

    tool_names = [t.name for t in (provider.received_tools or [])]
    assert "propose_change_plan" in tool_names
