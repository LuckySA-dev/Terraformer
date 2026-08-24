from __future__ import annotations

from app.assistant.client import ChatMessage
from app.assistant.service import _trim_to_context_limit


def _history(*roles_and_content: tuple[str, str]) -> list[ChatMessage]:
    return [ChatMessage(role=role, content=content) for role, content in roles_and_content]  # type: ignore[arg-type]


def test_no_limit_keeps_the_whole_history() -> None:
    history = _history(("system", "sys"), ("user", "a" * 10_000))

    assert _trim_to_context_limit(history, None) == history


def test_oldest_turns_are_dropped_to_fit_the_limit() -> None:
    history = _history(
        ("system", "sys"),
        ("user", "x" * 400),
        ("assistant", "y" * 400),
        ("user", "recent"),
    )

    # 100 tokens * 4 chars = 400 char budget; only the newest turn fits.
    trimmed = _trim_to_context_limit(history, 100)

    assert [m.role for m in trimmed] == ["system", "user"]
    assert trimmed[-1].content == "recent"


def test_the_system_message_survives_even_a_tiny_limit() -> None:
    history = _history(("system", "sys"), ("user", "x" * 500))

    trimmed = _trim_to_context_limit(history, 1)

    assert [m.role for m in trimmed] == ["system"]


def test_a_retained_window_never_starts_on_an_orphaned_tool_message() -> None:
    history = _history(
        ("system", "s"),
        ("assistant", "a" * 400),
        ("tool", "t"),
        ("user", "u"),
    )

    # Budget fits the tool result and the user turn, but not the assistant
    # turn that announced the call -- so the tool message must go too.
    trimmed = _trim_to_context_limit(history, 100)

    assert [m.role for m in trimmed] == ["system", "user"]
