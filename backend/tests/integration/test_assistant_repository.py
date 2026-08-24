from __future__ import annotations

from app.models import AssistantMessageRole, AssistantSessionMode, ProviderProfile
from app.repositories.assistant import AssistantMessageRepository, AssistantSessionRepository
from app.repositories.provider_profiles import ProviderProfileRepository


def test_create_session_defaults_to_confirm_mode(session_factory) -> None:
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1", model_id="llama3.1")
        )
        session.flush()
        created = AssistantSessionRepository(session).add(provider_profile_id=profile.id)
        session.commit()

        fetched = AssistantSessionRepository(session).get(created.id)
        assert fetched.mode is AssistantSessionMode.CONFIRM
        assert fetched.auto_apply_count == 0
        assert fetched.auto_mode_acknowledged_at is None


def test_messages_persist_in_order(session_factory) -> None:
    with session_factory() as session:
        profile = ProviderProfileRepository(session).add(
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1", model_id="llama3.1")
        )
        session.flush()
        sessions = AssistantSessionRepository(session)
        chat_session = sessions.add(provider_profile_id=profile.id)
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
            ProviderProfile(name="Local", base_url="http://localhost:11434/v1", model_id="llama3.1")
        )
        session.flush()
        sessions = AssistantSessionRepository(session)
        chat_session = sessions.add(provider_profile_id=profile.id)
        session.flush()

        sessions.set_mode(chat_session, AssistantSessionMode.AUTO)
        session.commit()

        fetched = sessions.get(chat_session.id)
        assert fetched.mode is AssistantSessionMode.AUTO
        assert fetched.auto_mode_acknowledged_at is not None
