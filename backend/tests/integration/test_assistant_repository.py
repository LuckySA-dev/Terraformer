from __future__ import annotations

from app.models import AssistantMessageRole, AssistantSessionMode, ProviderProfile
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.provider_profiles import ProviderProfileRepository


def test_create_session_defaults_to_confirm_mode(session_factory) -> None:
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1")
        )
        session.flush()
        created = AssistantSessionRepository(session).add(
            provider_profile_id=profile.id, model_id="llama3.1"
        )
        session.commit()

        fetched = AssistantSessionRepository(session).get(created.id)
        assert fetched.mode is AssistantSessionMode.CONFIRM
        assert fetched.auto_apply_count == 0
        assert fetched.auto_mode_acknowledged_at is None


def test_messages_persist_in_order(session_factory) -> None:
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1")
        )
        session.flush()
        sessions = AssistantSessionRepository(session)
        chat_session = sessions.add(provider_profile_id=profile.id, model_id="llama3.1")
        session.flush()

        messages = AssistantMessageRepository(session)
        messages.add(session_id=chat_session.id, role=AssistantMessageRole.USER, content="hello")
        messages.add(
            session_id=chat_session.id, role=AssistantMessageRole.ASSISTANT, content="hi there"
        )
        session.commit()

        history = messages.list_for_session(chat_session.id)
        assert [m.role for m in history] == [
            AssistantMessageRole.USER,
            AssistantMessageRole.ASSISTANT,
        ]
        assert [m.content for m in history] == ["hello", "hi there"]


def test_set_mode_requires_acknowledgment_timestamp_for_auto(session_factory) -> None:
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1")
        )
        session.flush()
        sessions = AssistantSessionRepository(session)
        chat_session = sessions.add(provider_profile_id=profile.id, model_id="llama3.1")
        session.flush()

        sessions.set_mode(chat_session, AssistantSessionMode.AUTO)
        session.commit()

        fetched = sessions.get(chat_session.id)
        assert fetched.mode is AssistantSessionMode.AUTO
        assert fetched.auto_mode_acknowledged_at is not None


def test_replay_order_survives_messages_sharing_a_timestamp(session_factory) -> None:
    """The exact case ordering by created_at could not answer.

    utc_now() has coarse enough resolution that consecutive inserts routinely
    share a value -- 941 distinct out of 2000 consecutive calls inside the
    application container -- and SQL leaves tied rows in an unspecified order.
    One of the possible orders puts a tool result ahead of the assistant turn
    that announced it, which the provider chat APIs reject outright.
    """
    from datetime import UTC, datetime

    frozen = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1")
        )
        session.flush()
        chat_session = AssistantSessionRepository(session).add(
            provider_profile_id=profile.id, model_id="llama3.1"
        )
        session.flush()

        messages = AssistantMessageRepository(session)
        turn = [
            (AssistantMessageRole.USER, "which ports are down?"),
            (AssistantMessageRole.ASSISTANT, ""),
            (AssistantMessageRole.TOOL, '{"interfaces": []}'),
            (AssistantMessageRole.ASSISTANT, "None of them."),
        ]
        for role, content in turn:
            stored = messages.add(session_id=chat_session.id, role=role, content=content)
            # Every message in the same instant, which is what the clock does
            # in practice often enough to matter.
            stored.created_at = frozen
        session.commit()

        replayed = messages.list_for_session(chat_session.id)
        assert [m.role for m in replayed] == [role for role, _ in turn]
        assert [m.content for m in replayed] == [content for _, content in turn]
        # Positions are dense and start at one, so a later message can never
        # sort ahead of an earlier one.
        assert [m.sequence for m in replayed] == [1, 2, 3, 4]


def test_each_conversation_numbers_its_own_messages(session_factory) -> None:
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1")
        )
        session.flush()
        sessions = AssistantSessionRepository(session)
        first = sessions.add(provider_profile_id=profile.id, model_id="llama3.1")
        second = sessions.add(provider_profile_id=profile.id, model_id="llama3.1")
        session.flush()

        messages = AssistantMessageRepository(session)
        messages.add(session_id=first.id, role=AssistantMessageRole.USER, content="a")
        messages.add(session_id=second.id, role=AssistantMessageRole.USER, content="b")
        messages.add(session_id=first.id, role=AssistantMessageRole.USER, content="c")
        session.commit()

        # A shared counter would make one conversation's numbering depend on
        # how busy the others were.
        assert [m.sequence for m in messages.list_for_session(first.id)] == [1, 2]
        assert [m.sequence for m in messages.list_for_session(second.id)] == [1]
