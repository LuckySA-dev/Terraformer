"""What happens when the assistant investigates for a while.

The system prompt tells the model to look before it answers, so a turn that
makes several rounds of tool calls is the normal case rather than the extreme
one. These cover what the loop does at its edges: when the budget runs out,
when the history grows, and when a model will not stop calling tools.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import ClassVar
from uuid import uuid4

import pytest

from app.assistant.client import ChatChunk, ChatMessage, ToolCallRequest, ToolSchema
from app.assistant.service import (
    _MAX_TOOL_CALLS_PER_TURN,
    _MAX_TOOL_ROUNDS_PER_TURN,
    AssistantChatService,
)
from app.assistant.tools import ToolResult
from app.models import AssistantSessionMode, ProviderType

pytestmark = pytest.mark.anyio


class _FakeSessions:
    def __init__(self, chat_session):
        self._chat_session = chat_session

    def get(self, session_id, *, for_update: bool = False):
        return self._chat_session


class _FakeMessages:
    def add(self, **_kwargs) -> None:
        pass

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
    scope_device_ids: ClassVar[list[str]] = []
    model_id = "test-model"
    supports_tool_calling = True
    context_limit_override = None
    mode = AssistantSessionMode.CONFIRM


class _BigPayloadDispatcher:
    """Stands in for get_topology on a network of any size."""

    def dispatch(self, name, arguments):
        return ToolResult(name=name, payload={"devices": ["x" * 400]})


class _RecordingProvider:
    """A model that always asks for one more tool, unless tools are withheld."""

    def __init__(self, *, calls_per_round: int = 1) -> None:
        self.rounds_seen = 0
        self.tools_offered: list[bool] = []
        self.history_sizes: list[int] = []
        self._calls_per_round = calls_per_round

    async def probe_capabilities(self, **_kwargs):
        raise AssertionError("not used")

    async def stream_chat(
        self,
        *,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
        **_kwargs,
    ) -> AsyncIterator[ChatChunk]:
        self.rounds_seen += 1
        self.tools_offered.append(tools is not None)
        self.history_sizes.append(sum(len(message.content) for message in messages))
        if tools is None:
            # Nothing left to call with, so it has to answer.
            yield ChatChunk(type="token", content="Here is what I found.")
            return
        for index in range(self._calls_per_round):
            yield ChatChunk(
                type="tool_call",
                tool_call=ToolCallRequest(
                    id=f"{self.rounds_seen}-{index}",
                    name="get_topology",
                    arguments={},
                ),
            )


def _service(provider, *, context_limit: int | None = None) -> AssistantChatService:
    chat_session = _Session()
    chat_session.context_limit_override = context_limit  # type: ignore[assignment]
    return AssistantChatService(
        session=_FakeDbSession(),  # type: ignore[arg-type]
        provider_client_for=lambda _provider_type: provider,
        sessions=_FakeSessions(chat_session),
        messages=_FakeMessages(),  # type: ignore[arg-type]
        profiles=_FakeProfiles(_Profile()),
        vault=_FakeVault(),  # type: ignore[arg-type]
        tools=_BigPayloadDispatcher(),  # type: ignore[arg-type]
    )


async def test_a_turn_that_spends_its_budget_still_answers() -> None:
    # It used to end on an error event and nothing else, leaving the operator
    # with their question and a pile of tool output.
    provider = _RecordingProvider()
    events = [e async for e in _service(provider).handle_user_message(uuid4(), "map the network")]

    assert [e.type for e in events][-1] == "done"
    assert "".join(e.content or "" for e in events if e.type == "token")
    assert not any(e.type == "error" for e in events)


async def test_the_last_round_withdraws_the_tools_so_the_model_must_answer() -> None:
    provider = _RecordingProvider()
    _ = [e async for e in _service(provider).handle_user_message(uuid4(), "map the network")]

    # Every round but the last offers tools; the last one cannot call any.
    assert provider.rounds_seen == _MAX_TOOL_ROUNDS_PER_TURN + 1
    assert provider.tools_offered[:-1] == [True] * _MAX_TOOL_ROUNDS_PER_TURN
    assert provider.tools_offered[-1] is False


async def test_a_model_that_answers_immediately_costs_one_round() -> None:
    class _Direct:
        async def probe_capabilities(self, **_kwargs):
            raise AssertionError("not used")

        async def stream_chat(self, **_kwargs) -> AsyncIterator[ChatChunk]:
            yield ChatChunk(type="token", content="No tools needed.")

    provider = _Direct()
    events = [e async for e in _service(provider).handle_user_message(uuid4(), "hello")]
    assert events[-1].type == "done"


async def test_history_is_trimmed_every_round_not_only_before_the_loop() -> None:
    # Each round appends an assistant turn and a tool result, and get_topology
    # is large. Trimming once meant a long investigation walked past the
    # model's context limit mid-turn and the provider rejected the request.
    bounded = _RecordingProvider()
    _ = [
        e
        async for e in _service(bounded, context_limit=200).handle_user_message(
            uuid4(), "map the network"
        )
    ]
    unbounded = _RecordingProvider()
    _ = [
        e
        async for e in _service(unbounded, context_limit=None).handle_user_message(
            uuid4(), "map the network"
        )
    ]

    # With a limit the conversation stays inside a ceiling of its own; with
    # none it grows every round. The contrast is what proves the trim runs
    # inside the loop rather than only ahead of it. The ceiling is the budget
    # plus the two things trimming may never drop -- the system prompt and the
    # operator's question.
    from app.assistant.service import SYSTEM_INSTRUCTIONS

    ceiling = 200 * 4 + len(SYSTEM_INSTRUCTIONS) + len("map the network")
    assert max(bounded.history_sizes) <= ceiling, bounded.history_sizes
    assert unbounded.history_sizes[-1] > max(bounded.history_sizes)
    assert unbounded.history_sizes[-1] > unbounded.history_sizes[0]


async def test_a_model_that_will_not_stop_calling_tools_is_capped() -> None:
    # Rounds alone do not bound the work: one round may announce any number of
    # calls, and each is a database read.
    provider = _RecordingProvider(calls_per_round=30)
    events = [e async for e in _service(provider).handle_user_message(uuid4(), "map everything")]

    dispatched = [e for e in events if e.type == "tool_call"]
    assert len(dispatched) <= _MAX_TOOL_CALLS_PER_TURN
    assert events[-1].type == "done"
