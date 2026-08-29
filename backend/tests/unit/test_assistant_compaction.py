"""Folding an old conversation into a summary instead of truncating it.

Dropping the oldest turns loses what they established -- the device that turned
out to be at fault, the value already checked, the thing ruled out. These cover
that the fold happens when it should, keeps the recent exchanges verbatim, and
never quietly blanks what it is carrying.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import ClassVar
from uuid import uuid4

import pytest

from app.assistant.client import ChatChunk, ChatMessage, ToolSchema
from app.assistant.service import (
    _KEEP_VERBATIM_MESSAGES,
    AssistantChatService,
)
from app.models import AssistantMessageRole, AssistantSessionMode, ProviderType

pytestmark = pytest.mark.anyio


class _StoredMessage:
    def __init__(self, role: AssistantMessageRole, content: str) -> None:
        self.role = role
        self.content = content
        self.tool_calls = None
        self.tool_results = None


class _FakeMessages:
    def __init__(self, messages: list[_StoredMessage]) -> None:
        self.messages = messages

    def add(self, *, session_id, role, content, tool_calls=None, tool_results=None) -> None:
        self.messages.append(_StoredMessage(role, content))

    def list_for_session(self, session_id):
        return self.messages


class _Session:
    id = uuid4()
    provider_profile_id = uuid4()
    device_id = None
    scope_device_ids: ClassVar[list[str]] = []
    model_id = "test-model"
    supports_tool_calling = False
    context_limit_override = None
    mode = AssistantSessionMode.CONFIRM
    summary: str | None = None
    summarised_message_count = 0


class _FakeSessions:
    def __init__(self, chat_session) -> None:
        self._chat_session = chat_session
        self.summaries: list[tuple[str, int]] = []

    def get(self, session_id, *, for_update: bool = False):
        return self._chat_session

    def set_summary(self, chat_session, *, summary: str, message_count: int) -> None:
        chat_session.summary = summary
        chat_session.summarised_message_count = message_count
        self.summaries.append((summary, message_count))


class _Profile:
    id = uuid4()
    base_url = "http://fake/v1"
    provider_type = ProviderType.OPENAI_COMPATIBLE


class _FakeProfiles:
    def get(self, profile_id):
        return _Profile()


class _FakeVault:
    def decrypt(self, profile):
        from app.services.provider_profiles import ProviderKeyMaterial

        return ProviderKeyMaterial(api_key=None)


class _FakeDbSession:
    def commit(self) -> None:
        pass


class _Provider:
    """Answers the summariser with a summary and everything else with a reply."""

    def __init__(self, *, summary: str = "SW1 Gi1/0/1 was found down.") -> None:
        self.summary = summary
        self.requests: list[list[ChatMessage]] = []

    async def probe_capabilities(self, **_kwargs):
        raise AssertionError("not used")

    async def stream_chat(
        self, *, messages: list[ChatMessage], tools: list[ToolSchema] | None = None, **_kwargs
    ) -> AsyncIterator[ChatChunk]:
        self.requests.append(messages)
        summarising = any("Summarise this network-operations" in m.content for m in messages)
        yield ChatChunk(type="token", content=self.summary if summarising else "ok")


def _service(provider, messages: _FakeMessages, sessions: _FakeSessions, *, limit: int = 32_000):
    return AssistantChatService(
        session=_FakeDbSession(),  # type: ignore[arg-type]
        provider_client_for=lambda _provider_type: provider,
        sessions=sessions,  # type: ignore[arg-type]
        messages=messages,  # type: ignore[arg-type]
        profiles=_FakeProfiles(),  # type: ignore[arg-type]
        vault=_FakeVault(),  # type: ignore[arg-type]
        tools=None,  # type: ignore[arg-type]
        context_limit_tokens=limit,
    )


def _long_conversation(turns: int = 20) -> list[_StoredMessage]:
    stored: list[_StoredMessage] = []
    for index in range(turns):
        stored.append(_StoredMessage(AssistantMessageRole.USER, f"question {index} " + "q" * 300))
        stored.append(
            _StoredMessage(AssistantMessageRole.ASSISTANT, f"answer {index} " + "a" * 300)
        )
    return stored


async def test_a_conversation_under_the_threshold_is_left_alone() -> None:
    sessions = _FakeSessions(_Session())
    provider = _Provider()
    messages = _FakeMessages([_StoredMessage(AssistantMessageRole.USER, "hello")])

    _ = [
        e
        async for e in _service(provider, messages, sessions).handle_user_message(
            uuid4(), "still hello"
        )
    ]

    assert sessions.summaries == []


async def test_crossing_the_threshold_folds_the_older_turns_into_a_summary() -> None:
    sessions = _FakeSessions(_Session())
    provider = _Provider()
    messages = _FakeMessages(_long_conversation())

    events = [
        e
        async for e in _service(provider, messages, sessions, limit=1_000).handle_user_message(
            uuid4(), "and now?"
        )
    ]

    assert sessions.summaries, "the conversation was never compacted"
    summary, folded = sessions.summaries[-1]
    assert summary == "SW1 Gi1/0/1 was found down."
    # The operator is told rather than silently losing the transcript.
    compacted = [e for e in events if e.type == "compacted"]
    assert len(compacted) == 1
    assert compacted[0].tool_payload == {"messages_folded": folded}


async def test_the_most_recent_exchanges_are_kept_verbatim() -> None:
    # Summarising the sentence the operator just replied to reads as the
    # assistant losing the thread. Compacted directly rather than through a
    # turn, so the message count is exactly what was set up here.
    sessions = _FakeSessions(_Session())
    provider = _Provider()
    stored = _long_conversation()
    messages = _FakeMessages(stored)

    await _service(provider, messages, sessions, limit=1_000).compact(uuid4())

    _, folded = sessions.summaries[-1]
    assert folded == len(stored) - _KEEP_VERBATIM_MESSAGES


async def test_the_summary_reaches_the_model_as_its_own_message() -> None:
    sessions = _FakeSessions(_Session())
    provider = _Provider()
    messages = _FakeMessages(_long_conversation())

    _ = [
        e
        async for e in _service(provider, messages, sessions, limit=1_000).handle_user_message(
            uuid4(), "and now?"
        )
    ]

    # The last request is the answering turn, not the summarising one.
    answering = provider.requests[-1]
    carried = [m for m in answering if "have been compacted" in m.content]
    assert len(carried) == 1
    assert "SW1 Gi1/0/1 was found down." in carried[0].content
    # And it is separate from the operating instructions, so the model can tell
    # what it was told to do from what it has already found out.
    assert answering[0].role == "system"
    assert "have been compacted" not in answering[0].content


async def test_compacting_twice_re_summarises_rather_than_stacking() -> None:
    chat_session = _Session()
    sessions = _FakeSessions(chat_session)
    provider = _Provider()
    stored = _long_conversation()
    messages = _FakeMessages(stored)
    service = _service(provider, messages, sessions, limit=1_000)

    _ = [e async for e in service.handle_user_message(uuid4(), "first")]
    first_summary_at = sessions.summaries[-1][1]
    messages.messages.extend(_long_conversation(6))
    _ = [e async for e in service.handle_user_message(uuid4(), "second")]

    assert len(sessions.summaries) == 2
    # The second fold covers strictly more of the conversation, and the model
    # was shown the previous summary rather than a summary of a summary.
    assert sessions.summaries[-1][1] > first_summary_at
    summarising = [
        request
        for request in provider.requests
        if any("Summarise this network-operations" in m.content for m in request)
    ]
    assert any(
        "A previous summary of still older turns" in m.content for m in summarising[-1]
    )


async def test_a_provider_returning_nothing_does_not_blank_the_summary() -> None:
    chat_session = _Session()
    chat_session.summary = "what we already knew"
    chat_session.summarised_message_count = 4
    sessions = _FakeSessions(chat_session)
    provider = _Provider(summary="   ")
    messages = _FakeMessages(_long_conversation())

    _ = [
        e
        async for e in _service(provider, messages, sessions, limit=1_000).handle_user_message(
            uuid4(), "and now?"
        )
    ]

    assert chat_session.summary == "what we already knew"
    assert sessions.summaries == []


async def test_compacting_on_request_reports_when_there_is_nothing_to_fold() -> None:
    # `/compact` on a short conversation must not spend a provider request
    # rewriting the same summary.
    sessions = _FakeSessions(_Session())
    provider = _Provider()
    messages = _FakeMessages([_StoredMessage(AssistantMessageRole.USER, "hello")])

    result = await _service(provider, messages, sessions).compact(uuid4())

    assert result is None
    assert provider.requests == []
