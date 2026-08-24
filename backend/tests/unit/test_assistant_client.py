from __future__ import annotations

import json

import httpx
import pytest

from app.assistant.client import AIProviderConnectionError, ChatMessage, OpenAICompatibleClient

pytestmark = pytest.mark.anyio


def _sse_body(chunks: list[dict[str, object]]) -> bytes:
    body = ""
    for chunk in chunks:
        body += f"data: {json.dumps(chunk)}\n\n"
    body += "data: [DONE]\n\n"
    return body.encode("utf-8")


def _chunk(content: str) -> dict[str, object]:
    return {
        "id": "1",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"content": content}}],
    }


def _completion() -> dict[str, object]:
    return {
        "id": "1",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "pong"},
                "finish_reason": "stop",
            }
        ],
    }


async def test_stream_chat_yields_tokens_then_done() -> None:
    chunks = [_chunk("Hel"), _chunk("lo")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_sse_body(chunks), headers={"content-type": "text/event-stream"}
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleClient(http_client=http_client)

    received = [
        chunk
        async for chunk in client.stream_chat(
            base_url="http://fake/v1",
            api_key=None,
            model_id="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            tools=None,
        )
    ]

    assert [c.content for c in received if c.type == "token"] == ["Hel", "lo"]
    assert received[-1].type == "done"


async def test_stream_chat_raises_connection_error_on_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleClient(http_client=http_client)

    with pytest.raises(AIProviderConnectionError):
        async for _chunk in client.stream_chat(
            base_url="http://fake/v1",
            api_key=None,
            model_id="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            tools=None,
        ):
            pass


async def test_probe_capabilities_reports_tool_calling_support() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion())

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleClient(http_client=http_client)

    capabilities = await client.probe_capabilities(
        base_url="http://fake/v1", api_key=None, model_id="test-model"
    )

    assert capabilities.supports_streaming is True
    assert capabilities.supports_tool_calling is True


async def test_probe_capabilities_falls_back_when_tools_param_rejected() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(400, json={"error": {"message": "tools not supported"}})
        return httpx.Response(200, json=_completion())

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleClient(http_client=http_client)

    capabilities = await client.probe_capabilities(
        base_url="http://fake/v1", api_key=None, model_id="test-model"
    )

    assert capabilities.supports_tool_calling is False
    assert capabilities.supports_streaming is True
