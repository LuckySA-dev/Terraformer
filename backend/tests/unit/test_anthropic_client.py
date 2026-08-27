from __future__ import annotations

import json

import httpx2
import pytest

from app.assistant.anthropic_client import (
    AnthropicClient,
    _split_system,
    _to_anthropic_messages,
)
from app.assistant.client import AIProviderConnectionError, ChatMessage

pytestmark = pytest.mark.anyio


def test_system_prompt_is_lifted_out_of_the_message_list() -> None:
    system, rest = _split_system(
        [
            ChatMessage(role="system", content="you are read-only"),
            ChatMessage(role="user", content="hi"),
        ]
    )

    assert system == "you are read-only"
    assert [m.role for m in rest] == ["user"]


def test_assistant_tool_calls_become_tool_use_blocks() -> None:
    converted = _to_anthropic_messages(
        [
            ChatMessage(
                role="assistant",
                content="Checking.",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_device_facts",
                            "arguments": json.dumps({"device_id": "abc"}),
                        },
                    }
                ],
            )
        ]
    )

    assert converted == [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Checking."},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "get_device_facts",
                    "input": {"device_id": "abc"},
                },
            ],
        }
    ]


def test_consecutive_tool_results_collapse_into_one_user_turn() -> None:
    converted = _to_anthropic_messages(
        [
            ChatMessage(role="tool", content='{"ok": 1}', tool_call_id="call_1"),
            ChatMessage(role="tool", content='{"ok": 2}', tool_call_id="call_2"),
        ]
    )

    assert len(converted) == 1
    assert converted[0]["role"] == "user"
    assert converted[0]["content"] == [
        {"type": "tool_result", "tool_use_id": "call_1", "content": '{"ok": 1}'},
        {"type": "tool_result", "tool_use_id": "call_2", "content": '{"ok": 2}'},
    ]


def test_a_trailing_tool_result_is_not_dropped() -> None:
    converted = _to_anthropic_messages(
        [
            ChatMessage(role="user", content="check it"),
            ChatMessage(role="tool", content='{"ok": 1}', tool_call_id="call_1"),
        ]
    )

    assert [m["role"] for m in converted] == ["user", "user"]
    assert converted[-1]["content"] == [
        {"type": "tool_result", "tool_use_id": "call_1", "content": '{"ok": 1}'}
    ]


def test_malformed_tool_arguments_do_not_crash_the_conversion() -> None:
    converted = _to_anthropic_messages(
        [
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "function": {"name": "get_device_facts", "arguments": "not json"},
                    }
                ],
            )
        ]
    )

    blocks = converted[0]["content"]
    assert isinstance(blocks, list)
    assert blocks[0]["input"] == {}


def _sse(events: list[dict[str, object]]) -> bytes:
    body = ""
    for event in events:
        body += f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
    return body.encode("utf-8")


def _text_stream_events() -> list[dict[str, object]]:
    return [
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hel"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "lo"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 2},
        },
        {"type": "message_stop"},
    ]


async def test_stream_chat_yields_tokens_then_done() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=_sse(_text_stream_events()),
            headers={"content-type": "text/event-stream"},
        )

    client = AnthropicClient(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )

    received = [
        chunk
        async for chunk in client.stream_chat(
            base_url="http://fake",
            api_key=None,
            model_id="claude-opus-5",
            messages=[
                ChatMessage(role="system", content="be brief"),
                ChatMessage(role="user", content="hi"),
            ],
            tools=None,
        )
    ]

    assert [c.content for c in received if c.type == "token"] == ["Hel", "lo"]
    assert received[-1].type == "done"


async def test_stream_chat_surfaces_tool_calls() -> None:
    events: list[dict[str, object]] = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "get_device_facts",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"device_id": "abc"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 2},
        },
        {"type": "message_stop"},
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, content=_sse(events), headers={"content-type": "text/event-stream"}
        )

    client = AnthropicClient(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )

    received = [
        chunk
        async for chunk in client.stream_chat(
            base_url="http://fake",
            api_key=None,
            model_id="claude-opus-5",
            messages=[ChatMessage(role="user", content="check abc")],
            tools=None,
        )
    ]

    calls = [c.tool_call for c in received if c.type == "tool_call"]
    assert len(calls) == 1
    assert calls[0] is not None
    assert calls[0].name == "get_device_facts"
    assert calls[0].arguments == {"device_id": "abc"}


async def test_stream_chat_raises_connection_error_on_network_failure() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    client = AnthropicClient(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )

    with pytest.raises(AIProviderConnectionError):
        async for _chunk in client.stream_chat(
            base_url="http://fake",
            api_key=None,
            model_id="claude-opus-5",
            messages=[ChatMessage(role="user", content="hi")],
            tools=None,
        ):
            pass


async def test_list_models_returns_sorted_model_ids() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "data": [
                    {
                        "id": "claude-sonnet-5",
                        "type": "model",
                        "display_name": "Sonnet",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    {
                        "id": "claude-opus-5",
                        "type": "model",
                        "display_name": "Opus",
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                ],
                "has_more": False,
                "first_id": None,
                "last_id": None,
            },
        )

    client = AnthropicClient(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )

    models = await client.list_models(base_url="http://fake", api_key=None)

    assert models == ["claude-opus-5", "claude-sonnet-5"]


async def test_probe_capabilities_reports_tool_calling_support() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [{"type": "text", "text": "pong"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = AnthropicClient(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )

    capabilities = await client.probe_capabilities(
        base_url="http://fake", api_key=None, model_id="claude-opus-5"
    )

    assert capabilities.supports_streaming is True
    assert capabilities.supports_tool_calling is True
