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


def test_the_question_survives_a_budget_too_small_to_hold_it() -> None:
    # This asserted that only the system message survived, which is what the
    # code did: the operator's question was dropped and the model was asked to
    # reply to instructions with nothing attached, so it answered a question
    # nobody had asked. Exceeding a limit the operator guessed at is
    # recoverable and the provider says so; this was not.
    history = _history(("system", "sys"), ("user", "x" * 500))

    trimmed = _trim_to_context_limit(history, 1)

    assert [m.role for m in trimmed] == ["system", "user"]
    assert trimmed[-1].content == "x" * 500


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


def test_a_long_investigation_keeps_the_newest_results_not_the_oldest() -> None:
    # Losing the oldest tool results of a turn costs the model detail it has
    # already reasoned over; losing the newest would cost it the thing it just
    # asked for and leave it looping on the same call.
    history = _history(
        ("system", "sys"),
        ("user", "map the network"),
        ("assistant", ""),
        ("tool", "oldest" + "x" * 400),
        ("assistant", ""),
        ("tool", "newest" + "y" * 400),
    )

    trimmed = _trim_to_context_limit(history, 150)

    contents = [message.content for message in trimmed]
    assert any(content.startswith("newest") for content in contents)
    assert not any(content.startswith("oldest") for content in contents)


def test_the_window_still_never_opens_on_an_orphaned_tool_result() -> None:
    # Trimming inside a turn can cut between an assistant turn and the result
    # it announced, which is exactly what the chat contract rejects.
    history = _history(
        ("system", "sys"),
        ("user", "map the network"),
        ("assistant", "z" * 400),
        ("tool", "y" * 100),
    )

    # Room for the tool result but not the assistant turn that announced it,
    # so the result is dropped rather than left dangling.
    trimmed = _trim_to_context_limit(history, 30)

    assert [m.role for m in trimmed] == ["system", "user"]


def test_earlier_turns_are_only_carried_once_this_one_fits_whole() -> None:
    history = _history(
        ("system", "sys"),
        ("user", "an older question"),
        ("assistant", "an older answer"),
        ("user", "the current question"),
        ("assistant", ""),
        ("tool", "t" * 600),
    )

    # The current turn alone overruns, so nothing older comes with it.
    trimmed = _trim_to_context_limit(history, 100)
    assert [m.content for m in trimmed if m.role == "user"] == ["the current question"]

    # With room for everything, the earlier exchange is kept.
    roomy = _trim_to_context_limit(history, 10_000)
    assert len(roomy) == len(history)
