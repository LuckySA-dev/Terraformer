from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.assistant.client import AIProviderClient, ChatMessage, ToolCallRequest
from app.assistant.sanitize import scrub_secrets
from app.assistant.tools import (
    PROPOSE_CHANGE_PLAN_TOOL,
    READ_ONLY_TOOLS,
    ReadOnlyToolError,
    ToolDispatcher,
    ToolSchema,
)
from app.changes.service import ChangeService
from app.core.errors import AppError, AutoModeRequiresAcknowledgmentError, ChangeValidationError
from app.models import (
    AssistantMessage,
    AssistantMessageRole,
    AssistantSession,
    AssistantSessionMode,
    ChangePlanSource,
    ChangeType,
    ProviderType,
)
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.provider_profiles import ProviderProfileRepository
from app.services.devices import DeviceService
from app.services.provider_profiles import ProviderKeyVault

# An agent told to investigate before it answers needs more than a couple of
# round trips: "which ports on SW1 are down" is a list_devices then a read, and
# anything comparing two devices is more. The cap is a runaway guard, not a
# budget the operator should feel, so it is set well above normal use.
_MAX_TOOL_ROUNDS_PER_TURN = 12
# Rounds alone do not bound the work: one round may announce any number of
# calls. Each is a database read, but a model looping on a malformed argument
# could still spend the turn making them.
_MAX_TOOL_CALLS_PER_TURN = 40


# Rough characters-per-token ratio. Counting exactly would mean shipping a
# tokenizer per model family; this is a deliberate approximation used only to
# decide when to drop the oldest turns, so erring small just trims earlier.
_CHARS_PER_TOKEN = 4


# Written as operating instructions rather than a personality: the difference
# between a chat window that knows about networking and a tool that does the
# work is almost entirely whether it looks before it answers.
SYSTEM_INSTRUCTIONS = """You are the network engineer inside Terraformer, a tool for
operating real network devices. You are not a chat assistant that happens to know
networking -- you are expected to go and look.

## How to work

Look first. You have read-only tools over everything this application has observed.
Call them before answering anything about this network; never guess a device name, an
interface, a VLAN id or an address that a tool could have told you. `list_devices`,
`get_topology` and `list_change_plans` take no arguments and are where to start:
the per-device tools need a device_id, and those are the only way to learn one.

Chain tools without asking permission. Reading is free and never touches a device's
configuration. Stop to ask only when the request is genuinely ambiguous about intent,
never when you are missing a fact you could have looked up. Ask for everything a step
needs in one go rather than one call at a time -- a turn has a bounded number of
rounds, and several calls in one round cost one round between them.

Say what the evidence is. Everything you read is observed state as of each device's
last refresh, which `last_seen_at` reports. If a device has not been refreshed
recently, say so rather than presenting stale data as current. If a tool returns
nothing, say it returned nothing -- do not fill the gap.

Be concise and concrete. Lead with the answer. Name devices and interfaces exactly as
the device reports them. Prefer a short list or table over prose. No preamble, no
restating the question, no narrating what you are about to do.

## Changing things

You cannot write to a device. `propose_change_plan` drafts and validates a plan
through the same pipeline a human preview uses; applying it is a separate step that a
human either confirms or has explicitly delegated by putting this session in Auto
mode. In Auto mode the operator accepted that risk in advance -- that is their
decision, not a reason to add confirmation prompts of your own, and not a reason to be
less careful about what you propose.

One plan is one change on one device. To change several things, or several devices,
propose several plans. Before proposing, read the current state of what you are about
to change, and say what it is now and what it will become. When something is broken,
check `list_change_plans` first -- a recent failed or rolled-back plan is often the
answer.

The pipeline refuses a change that would do nothing, and refuses one it cannot undo.
Those refusals are the design working, not obstacles to route around. If a plan is
rejected, read the reason back to the operator plainly instead of retrying variations.

## Console commands

Some things have no change type yet. When the right answer is a command the operator
runs themselves, put it in a fenced code block by itself, with no other text inside
the fence, and say what it does and what it would take to undo it. Never present a
console command as though you had run it."""


def _drop_leading_orphan(messages: list[ChatMessage]) -> list[ChatMessage]:
    """A window may not open on a tool result whose announcing turn is gone."""
    while messages and messages[0].role == "tool":
        messages.pop(0)
    return messages


def _trim_to_context_limit(
    history: list[ChatMessage], limit_tokens: int | None
) -> list[ChatMessage]:
    """Drops the oldest turns until the conversation fits the profile's limit.

    Two things are never dropped. The system message, and the newest user
    message -- the request being answered. A budget smaller than the system
    prompt plus that question used to fit nothing at all, so the model was
    asked to reply to instructions with no request attached, and answered a
    question nobody had asked. Going over a limit the operator guessed at is
    recoverable and the provider reports it plainly; sending a conversation
    with the question removed is neither.

    Everything else is negotiable, newest first: this turn's own tool results
    before the turns that came before it. A window never opens on a tool
    result whose announcing assistant turn was trimmed away, which is exactly
    what the chat contract rejects.
    """
    if limit_tokens is None or not history:
        return history
    budget = limit_tokens * _CHARS_PER_TOKEN
    system, rest = history[0], history[1:]
    if not rest:
        return history

    request_at = next(
        (index for index in range(len(rest) - 1, -1, -1) if rest[index].role == "user"),
        len(rest) - 1,
    )
    request = rest[request_at]
    turn, earlier = rest[request_at + 1 :], rest[:request_at]
    used = len(system.content) + len(request.content)

    # This turn's work, newest first. Losing the oldest tool results of a long
    # investigation costs the model detail it has already reasoned over; losing
    # the newest would cost it the thing it just asked for.
    kept_turn: list[ChatMessage] = []
    for message in reversed(turn):
        cost = len(message.content)
        if used + cost > budget:
            break
        used += cost
        kept_turn.append(message)
    kept_turn.reverse()
    kept_turn = _drop_leading_orphan(kept_turn)

    # Earlier turns are only worth carrying once the current one fits whole.
    kept_earlier: list[ChatMessage] = []
    if len(kept_turn) == len(turn):
        for message in reversed(earlier):
            cost = len(message.content)
            if used + cost > budget:
                break
            used += cost
            kept_earlier.append(message)
        kept_earlier.reverse()
        kept_earlier = _drop_leading_orphan(kept_earlier)

    return [system, *kept_earlier, request, *kept_turn]


def _announced_tool_calls(calls: list[ToolCallRequest]) -> list[dict[str, object]]:
    """Storage shape for the tool calls one assistant turn announced."""
    return [{"id": call.id, "name": call.name, "arguments": call.arguments} for call in calls]


def _to_openai_tool_calls(announced: list[dict[str, object]]) -> list[dict[str, object]]:
    """Storage shape -> the wire shape the chat contract expects back."""
    return [
        {
            "id": call.get("id", ""),
            "type": "function",
            "function": {
                "name": call.get("name", ""),
                "arguments": json.dumps(call.get("arguments", {})),
            },
        }
        for call in announced
    ]


@dataclass(frozen=True, slots=True)
class AssistantEvent:
    type: Literal["token", "tool_call", "tool_result", "change_plan_proposed", "done", "error"]
    content: str | None = None
    tool_name: str | None = None
    tool_payload: dict[str, object] | None = None
    error_code: str | None = None


class AssistantChatService:
    def __init__(
        self,
        session: Session,
        *,
        provider_client_for: Callable[[ProviderType], AIProviderClient],
        sessions: AssistantSessionRepository,
        messages: AssistantMessageRepository,
        profiles: ProviderProfileRepository,
        vault: ProviderKeyVault,
        tools: ToolDispatcher,
        changes: ChangeService | None = None,
        devices: DeviceService | None = None,
    ) -> None:
        self._session = session
        self._provider_client_for = provider_client_for
        self._sessions = sessions
        self._messages = messages
        self._profiles = profiles
        self._vault = vault
        self._tools = tools
        self._changes = changes
        self._devices = devices

    async def handle_user_message(
        self, session_id: UUID, content: str
    ) -> AsyncIterator[AssistantEvent]:
        chat_session = self._sessions.get(session_id)
        profile = self._profiles.get(chat_session.provider_profile_id)
        material = self._vault.decrypt(profile)

        self._messages.add(session_id=session_id, role=AssistantMessageRole.USER, content=content)
        self._session.commit()

        history = _trim_to_context_limit(
            self._build_history(
                session_id, chat_session.device_id, chat_session.scope_device_ids
            ),
            chat_session.context_limit_override,
        )
        tool_schemas: list[ToolSchema] | None = (
            list(READ_ONLY_TOOLS) if chat_session.supports_tool_calling else None
        )
        if tool_schemas is not None and self._changes is not None:
            tool_schemas = [*tool_schemas, PROPOSE_CHANGE_PLAN_TOOL]

        calls_made = 0
        # One extra pass with the tools withdrawn. A turn that spends its
        # budget used to end on an error and no answer at all, which left the
        # operator with a question and a stack of tool output; now the model is
        # made to answer from what it already read.
        for round_index in range(_MAX_TOOL_ROUNDS_PER_TURN + 1):
            final_round = round_index == _MAX_TOOL_ROUNDS_PER_TURN
            if final_round:
                history.append(
                    ChatMessage(
                        role="system",
                        content=(
                            "The tool budget for this turn is spent. Answer now from what you "
                            "have already read, and say plainly which part of the question you "
                            "could not finish looking into."
                        ),
                    )
                )
            # Re-trimmed every round, not once before the loop: each round adds
            # an assistant turn and a tool result, and a tool that returns the
            # whole topology can be large. Without this a long investigation
            # walks past the model's context limit mid-turn and the provider
            # rejects the request.
            history = _trim_to_context_limit(history, chat_session.context_limit_override)
            reply_text = ""
            pending_tool_calls: list[ToolCallRequest] = []
            async for chunk in self._provider_client_for(profile.provider_type).stream_chat(
                base_url=profile.base_url,
                api_key=material.api_key,
                model_id=chat_session.model_id,
                messages=history,
                tools=None if final_round else tool_schemas,
            ):
                if chunk.type == "token" and chunk.content:
                    reply_text += chunk.content
                    yield AssistantEvent(type="token", content=chunk.content)
                elif chunk.type == "tool_call" and chunk.tool_call is not None:
                    pending_tool_calls.append(chunk.tool_call)

            # Persisted even when reply_text is empty, as long as tool calls
            # were made: the tool messages below are only valid in a replayed
            # conversation if the assistant turn that announced them is there
            # too.
            if reply_text or pending_tool_calls:
                announced = _announced_tool_calls(pending_tool_calls)
                self._messages.add(
                    session_id=session_id,
                    role=AssistantMessageRole.ASSISTANT,
                    content=reply_text,
                    tool_calls={"calls": announced} if announced else None,
                )
                self._session.commit()
                history.append(
                    ChatMessage(
                        role="assistant",
                        content=reply_text,
                        tool_calls=_to_openai_tool_calls(announced) if announced else None,
                    )
                )

            if not pending_tool_calls:
                yield AssistantEvent(type="done")
                return

            for call in pending_tool_calls:
                calls_made += 1
                if calls_made > _MAX_TOOL_CALLS_PER_TURN:
                    break
                yield AssistantEvent(
                    type="tool_call", tool_name=call.name, tool_payload=call.arguments
                )
                payload: dict[str, object]
                event_type: Literal["tool_result", "change_plan_proposed"] = "tool_result"
                changes = self._changes
                if call.name == PROPOSE_CHANGE_PLAN_TOOL.name and changes is not None:
                    payload = self._propose_change_plan(changes, call.arguments)
                    if "plan_id" in payload:
                        event_type = "change_plan_proposed"
                else:
                    try:
                        result = self._tools.dispatch(call.name, call.arguments)
                        payload = cast("dict[str, object]", scrub_secrets(result.payload))
                    except ReadOnlyToolError as exc:
                        payload = {"error": str(exc)}
                yield AssistantEvent(type=event_type, tool_name=call.name, tool_payload=payload)
                encoded_payload = json.dumps(payload)
                self._messages.add(
                    session_id=session_id,
                    role=AssistantMessageRole.TOOL,
                    content=encoded_payload,
                    tool_calls={"tool_call_id": call.id},
                    tool_results=payload,
                )
                self._session.commit()
                history.append(
                    ChatMessage(role="tool", content=encoded_payload, tool_call_id=call.id)
                )
            if calls_made > _MAX_TOOL_CALLS_PER_TURN:
                break

        # Only reachable if the final tools-withdrawn round still announced
        # tool calls, which a provider should not do. Ending on `done` keeps
        # the socket contract intact either way.
        yield AssistantEvent(type="done")

    @staticmethod
    def _propose_change_plan(
        changes: ChangeService, arguments: dict[str, object]
    ) -> dict[str, object]:
        try:
            device_id = UUID(str(arguments["device_id"]))
            change_type = ChangeType(str(arguments["change_type"]))
            target = str(arguments["target"])
            desired_value = str(arguments["desired_value"])
        except (KeyError, ValueError) as exc:
            return {"error": f"Malformed change plan proposal: {exc}"}
        try:
            plan = changes.preview(
                device_id=device_id,
                change_type=change_type,
                target=target,
                desired_value=desired_value,
                source=ChangePlanSource.AI_GENERATED,
            )
        except AppError as exc:
            payload: dict[str, object] = {"error": str(exc)}
            if isinstance(exc, ChangeValidationError):
                payload["issues"] = exc.details.get("issues", [])
            return payload
        return {
            "plan_id": str(plan.id),
            "status": plan.status.value,
            "risk": plan.risk.value,
            "safety_level": plan.safety_level.value,
            "steps": [
                {
                    "target": s.target,
                    "desired_value": s.desired_value,
                    "rendered_commands": s.rendered_commands,
                }
                for s in plan.steps
            ],
        }

    @staticmethod
    def _replay(message: AssistantMessage) -> ChatMessage:
        stored_calls = message.tool_calls or {}
        if message.role is AssistantMessageRole.TOOL:
            tool_call_id = stored_calls.get("tool_call_id")
            return ChatMessage(
                role="tool",
                content=message.content,
                tool_call_id=str(tool_call_id) if tool_call_id is not None else None,
            )
        if message.role is AssistantMessageRole.ASSISTANT:
            announced = cast("list[dict[str, object]]", stored_calls.get("calls", []))
            return ChatMessage(
                role="assistant",
                content=message.content,
                tool_calls=_to_openai_tool_calls(announced) if announced else None,
            )
        return ChatMessage(role=message.role.value, content=message.content)

    def _device_context(self, device_id: UUID) -> str:
        """Name the device this conversation is pinned to.

        Without it a device-scoped chat is useless in practice: every tool
        takes a device_id, and the operator would have to paste a UUID into
        the chat to ask about the device whose page they are already on.
        """
        header = f'This conversation is about the device with device_id "{device_id}".'
        if self._devices is None:
            return header
        try:
            device = self._devices.get(device_id)
        except AppError:
            # The device was removed mid-conversation. The chat itself is
            # still readable, so degrade to the id rather than failing.
            return header
        return (
            f"{header} It is named {device.name}, a {device.vendor.value} device at "
            f"{device.management_address}. Use that device_id for tool calls unless "
            "the operator names a different device."
        )

    def _scope_context(self, scope_device_ids: list[str]) -> str:
        """Name the devices the operator selected in the sidebar.

        The point is the same as `_device_context`: let the operator say "shut
        SW1 and SW2 down" without pasting two UUIDs. This is context, not
        enforcement -- the tools still take an explicit device_id and every
        change still needs a preview and a human confirmation, so a model that
        reaches outside this list is wrong rather than dangerous.
        """
        named: list[str] = []
        for raw in scope_device_ids:
            if self._devices is None:
                named.append(f'device_id "{raw}"')
                continue
            try:
                device = self._devices.get(UUID(raw))
            except (AppError, ValueError):
                # Removed mid-conversation, or an id that no longer parses.
                continue
            named.append(f'{device.name} (device_id "{device.id}")')
        if not named:
            return ""
        return (
            "The operator has scoped this conversation to these devices: "
            f"{', '.join(named)}. Treat them as the subject of requests that do "
            "not name a device, and ask before acting on any device outside "
            "this list."
        )

    def _build_history(
        self,
        session_id: UUID,
        device_id: UUID | None = None,
        scope_device_ids: list[str] | None = None,
    ) -> list[ChatMessage]:
        stored = self._messages.list_for_session(session_id)
        instructions = SYSTEM_INSTRUCTIONS
        if device_id is not None:
            instructions = f"{instructions}\n\n{self._device_context(device_id)}"
        elif scope_device_ids:
            scope = self._scope_context(scope_device_ids)
            if scope:
                instructions = f"{instructions}\n\n{scope}"
        return [
            ChatMessage(role="system", content=instructions),
            *(self._replay(m) for m in stored),
        ]

    def set_mode(
        self, session_id: UUID, mode: AssistantSessionMode, *, risk_acknowledged: bool
    ) -> AssistantSession:
        chat_session = self._sessions.get(session_id, for_update=True)
        if mode is AssistantSessionMode.AUTO and not risk_acknowledged:
            raise AutoModeRequiresAcknowledgmentError()
        self._sessions.set_mode(chat_session, mode)
        self._session.commit()
        return chat_session
