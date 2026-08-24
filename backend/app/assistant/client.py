from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, cast

import httpx
from openai import NOT_GIVEN, APIConnectionError, APIStatusError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from pydantic import BaseModel

_PROBE_TOOL = cast(
    "ChatCompletionToolParam",
    {
        "type": "function",
        "function": {
            "name": "_capability_probe",
            "description": "Unused -- presence alone tests whether tool schemas are accepted.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ChatChunk:
    type: Literal["token", "tool_call", "done"]
    content: str | None = None
    tool_call: ToolCallRequest | None = None


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supports_streaming: bool
    supports_tool_calling: bool


class AIProviderConnectionError(Exception):
    pass


class AIProviderClient(Protocol):
    async def probe_capabilities(
        self, *, base_url: str, api_key: str | None, model_id: str
    ) -> ProviderCapabilities: ...

    def stream_chat(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_id: str,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None,
    ) -> AsyncIterator[ChatChunk]: ...


def _to_openai_tool(tool: ToolSchema) -> ChatCompletionToolParam:
    return cast(
        "ChatCompletionToolParam",
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        },
    )


_PING_MESSAGE = cast(
    "list[ChatCompletionMessageParam]", [{"role": "user", "content": "ping"}]
)


class OpenAICompatibleClient:
    """Thin translation layer over the official openai SDK, pointed at a
    caller-supplied base_url. This process never runs or bundles a model --
    every call is a proxy to whatever endpoint the ProviderProfile names."""

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client

    def _client(self, *, base_url: str, api_key: str | None) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=base_url, api_key=api_key or "not-required", http_client=self._http_client
        )

    async def probe_capabilities(
        self, *, base_url: str, api_key: str | None, model_id: str
    ) -> ProviderCapabilities:
        client = self._client(base_url=base_url, api_key=api_key)
        try:
            await client.chat.completions.create(
                model=model_id,
                messages=_PING_MESSAGE,
                max_tokens=1,
                tools=[_PROBE_TOOL],
                tool_choice="none",
            )
        except APIConnectionError as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        except APIStatusError as exc:
            if exc.status_code in (400, 404, 422):
                return await self._probe_without_tools(client, model_id)
            raise AIProviderConnectionError(str(exc)) from exc
        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=True)

    async def _probe_without_tools(
        self, client: AsyncOpenAI, model_id: str
    ) -> ProviderCapabilities:
        try:
            await client.chat.completions.create(
                model=model_id, messages=_PING_MESSAGE, max_tokens=1
            )
        except (APIConnectionError, APIStatusError) as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        return ProviderCapabilities(supports_streaming=True, supports_tool_calling=False)

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
        payload_messages = cast(
            "list[ChatCompletionMessageParam]",
            [m.model_dump(exclude_none=True) for m in messages],
        )
        openai_tools = [_to_openai_tool(t) for t in tools] if tools else None
        try:
            stream = await client.chat.completions.create(
                model=model_id,
                messages=payload_messages,
                stream=True,
                tools=openai_tools if openai_tools else NOT_GIVEN,
            )
            async for event in stream:
                delta = event.choices[0].delta
                if delta.content:
                    yield ChatChunk(type="token", content=delta.content)
                if delta.tool_calls:
                    for call in delta.tool_calls:
                        if call.function is None:
                            continue
                        yield ChatChunk(
                            type="tool_call",
                            tool_call=ToolCallRequest(
                                id=call.id or "",
                                name=call.function.name or "",
                                arguments=json.loads(call.function.arguments or "{}"),
                            ),
                        )
        except APIConnectionError as exc:
            raise AIProviderConnectionError(str(exc)) from exc
        yield ChatChunk(type="done")
