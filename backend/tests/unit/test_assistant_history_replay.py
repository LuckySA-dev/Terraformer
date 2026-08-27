"""Regression tests for rebuilding chat history out of persisted messages.

The OpenAI chat contract is strict about tool exchanges: every
`role="tool"` message must carry the `tool_call_id` it answers, and must be
preceded by an `role="assistant"` message whose `tool_calls` announced it.
A turn-one tool call works off the in-memory history; the bug these tests
pin down only appears on turn two, when history is rebuilt from the
database.
"""

from __future__ import annotations

from uuid import uuid4

from app.assistant.service import AssistantChatService
from app.models import AssistantMessageRole


class _StoredMessage:
    def __init__(self, role, content, tool_calls=None, tool_results=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_results = tool_results


class _ReplayMessages:
    def __init__(self, stored: list[_StoredMessage]):
        self._stored = stored

    def add(self, **_kwargs):
        raise AssertionError("not used")

    def list_for_session(self, _session_id):
        return self._stored


def _service_with(stored: list[_StoredMessage]) -> AssistantChatService:
    return AssistantChatService(
        session=None,  # type: ignore[arg-type]
        provider_client_for=None,  # type: ignore[arg-type]
        sessions=None,  # type: ignore[arg-type]
        messages=_ReplayMessages(stored),  # type: ignore[arg-type]
        profiles=None,  # type: ignore[arg-type]
        vault=None,  # type: ignore[arg-type]
        tools=None,  # type: ignore[arg-type]
    )


def test_replayed_tool_message_keeps_its_tool_call_id() -> None:
    service = _service_with(
        [
            _StoredMessage(AssistantMessageRole.USER, "check the edge router"),
            _StoredMessage(
                AssistantMessageRole.ASSISTANT,
                "",
                tool_calls={
                    "calls": [
                        {
                            "id": "call_1",
                            "name": "get_device_facts",
                            "arguments": {"device_id": "x"},
                        }
                    ]
                },
            ),
            _StoredMessage(
                AssistantMessageRole.TOOL,
                '{"facts": {"hostname": "r1"}}',
                tool_calls={"tool_call_id": "call_1"},
            ),
        ]
    )

    history = service._build_history(uuid4())

    tool_messages = [m for m in history if m.role == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_1"


def test_replayed_assistant_message_keeps_the_tool_calls_it_announced() -> None:
    service = _service_with(
        [
            _StoredMessage(AssistantMessageRole.USER, "check the edge router"),
            _StoredMessage(
                AssistantMessageRole.ASSISTANT,
                "",
                tool_calls={
                    "calls": [
                        {
                            "id": "call_1",
                            "name": "get_device_facts",
                            "arguments": {"device_id": "x"},
                        }
                    ]
                },
            ),
        ]
    )

    history = service._build_history(uuid4())

    assistant = next(m for m in history if m.role == "assistant")
    assert assistant.tool_calls is not None
    assert assistant.tool_calls[0]["id"] == "call_1"
    assert assistant.tool_calls[0]["type"] == "function"
    assert assistant.tool_calls[0]["function"]["name"] == "get_device_facts"


def test_plain_messages_replay_without_tool_fields() -> None:
    service = _service_with(
        [
            _StoredMessage(AssistantMessageRole.USER, "hello"),
            _StoredMessage(AssistantMessageRole.ASSISTANT, "hi there"),
        ]
    )

    history = service._build_history(uuid4())

    assert [m.role for m in history] == ["system", "user", "assistant"]
    assert all(m.tool_call_id is None for m in history)
    assert all(m.tool_calls is None for m in history)
