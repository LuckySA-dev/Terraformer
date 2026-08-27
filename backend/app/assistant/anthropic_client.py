from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

import httpx2
from anthropic import APIConnectionError, APIStatusError, AsyncAnthropic, omit

from app.assistant.client import (
    AIProviderConnectionError,
    ChatChunk,
    ChatMessage,
    ProviderCapabilities,
    ToolCallRequest,
    ToolSchema,
)

# Every Claude model accepts at least this many output tokens, including the
# older Claude 3 family a user may still name. The assistant answers questions
# about devices and drafts short Change Plans, so this is ample.
# ponytail: fixed ceiling rather than a per-model lookup; make it a setting if
# someone genuinely needs longer answers.
_MAX_OUTPUT_TOKENS = 4096

_PROBE_TOOL: dict[str, object] = {
    "name": "_capability_probe",
    "description": "Unused -- presence alone tests whether tool schemas are accepted.",
    "input_schema": {"type": "object", "properties": {}},
}


def _to_anthropic_tool(tool: ToolSchema) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters,
    }


def _split_system(messages: list[ChatMessage]) -> tuple[str | None, list[ChatMessage]]:
    """Anthropic takes the system prompt as a top-level parameter, not a message."""
    system_parts = [m.content for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    return ("\n\n".join(system_parts) or None), rest


def _to_anthropic_messages(messages: list[ChatMessage]) -> list[dict[str, object]]:
    """Translate the stored OpenAI-shaped history into Anthropic's block format.

    Three shapes differ and all three matter for replaying a tool exchange:
    an assistant turn announces calls as `tool_use` content blocks rather than
    a sibling `tool_calls` array, a tool result is a `user` turn carrying a
    `tool_result` block rather than its own `tool` role, and consecutive tool
    results belong in one user turn -- splitting them across turns teaches the
    model to stop making parallel calls.
    """
    converted: list[dict[str, object]] = []
    pending_tool_results: list[dict[str, object]] = []

    def flush_tool_results() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            converted.append({"role": "user", "content": pending_tool_results})
            pending_tool_results = []

    for message in messages:
        if message.role == "tool":
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content,
                }
            )
            continue

        flush_tool_results()

        if message.role == "assistant":
            blocks: list[dict[str, object]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls or []:
                function = cast("dict[str, object]", call.get("function", {}))
                raw_arguments = function.get("arguments", "{}")
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(call.get("id", "")),
                        "name": str(function.get("name", "")),
                        "input": _decode_arguments(raw_arguments),
                    }
                )
            # An assistant turn with neither text nor calls is not a legal
            # turn; drop it rather than have the whole conversation rejected.
            if blocks:
                converted.append({"role": "assistant", "content": blocks})
            continue

        converted.append({"role": "user", "content": message.content})

    flush_tool_results()
    return converted


def _decode_arguments(raw: object) -> dict[str, object]:
    import json

    if isinstance(raw, dict):
        return cast("dict[str, object]", raw)
    try:
        decoded = json.loads(str(raw) or "{}")
    except json.JSONDecodeError:
        return {}
    return cast("dict[str, object]", decoded) if isinstance(decoded, dict) else {}


class AnthropicClient:
    """Adapter for Anthropic's own Messages API.

    A sibling of OpenAICompatibleClient, not a replacement: Anthropic speaks a
    different wire format, so a direct Anthropic key cannot be served by
    pointing the OpenAI client at a different base URL. This process still
    never runs or bundles a model -- every call proxies to the endpoint the
    ProviderProfile names.
    """

    def __init__(self, *, http_client: httpx2.AsyncClient | None = None) -> None:
        self._http_client = http_client

    def _client(self, *, base_url: str, api_key: str | None) -> AsyncAnthropic:
        return AsyncAnthropic(
            base_url=base_url,
            api_key=api_key or "not-required",
            http_client=self._http_client,
        )

    async def probe_capabilities(
        self, *, base_url: str, api_key: str | None, model_id: str
    ) -> ProviderCapabilities:
        client = self._client(base_url=base_url, api_key=api_key)
        try:
            await client.messages.create(
                model=model_id,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
                tools=[cast("object", _PROBE_TOOL)],  # type: ignore[list-item]
            )
        except APIConnectionError as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        except APIStatusError as exc:
            if exc.status_code in (400, 404, 422):
                return await self._probe_without_tools(client, model_id)
            raise AIProviderConnectionError(str(exc)) from exc
        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=True)

    async def _probe_without_tools(
        self, client: AsyncAnthropic, model_id: str
    ) -> ProviderCapabilities:
        try:
            await client.messages.create(
                model=model_id,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
        except (APIConnectionError, APIStatusError) as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=False)

    async def list_models(self, *, base_url: str, api_key: str | None) -> list[str]:
        client = self._client(base_url=base_url, api_key=api_key)
        try:
            models = [model.id async for model in client.models.list()]
        except (APIConnectionError, APIStatusError) as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        return sorted(models)

    async def stream_chat(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None,
    ) -> AsyncIterator[ChatChunk]:
        client = self._client(base_url=base_url, api_key=api_key)
        system, conversation = _split_system(messages)
        anthropic_tools = [_to_anthropic_tool(t) for t in tools] if tools else None
        try:
            async with client.messages.stream(
                model=model_id,
                max_tokens=_MAX_OUTPUT_TOKENS,
                system=system if system is not None else omit,
                messages=cast("list[object]", _to_anthropic_messages(conversation)),  # type: ignore[arg-type]
                tools=cast("list[object]", anthropic_tools) if anthropic_tools else omit,  # type: ignore[arg-type]
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield ChatChunk(type="token", content=event.delta.text)
                final = await stream.get_final_message()
        except APIConnectionError as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        except APIStatusError as exc:
            raise AIProviderConnectionError(str(exc)) from exc

        # Tool inputs are read off the assembled final message rather than
        # rebuilt from partial input_json deltas -- the SDK has already
        # parsed them, so there is no half-written JSON to guess at.
        for block in final.content:
            if block.type == "tool_use":
                yield ChatChunk(
                    type="tool_call",
                    tool_call=ToolCallRequest(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    ),
                )
        yield ChatChunk(type="done")
