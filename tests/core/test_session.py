"""Tests for session persistence."""

import pytest

from birkin.core.models import Message
from birkin.core.session import Session, SessionStore


@pytest.fixture
def store():
    """Provide an in-memory SessionStore."""
    return SessionStore(":memory:")


class TestSession:
    def test_creates_with_unique_id(self):
        s1 = Session.new()
        s2 = Session.new()
        assert s1.id != s2.id

    def test_new_has_current_timestamp(self):
        s = Session.new()
        assert s.created_at is not None

    def test_with_metadata(self):
        s = Session.new(
            title="My Chat",
            provider="anthropic",
            model="claude-sonnet-4-6",
        )
        assert s.title == "My Chat"
        assert s.provider == "anthropic"
        assert s.model == "claude-sonnet-4-6"


class TestSessionStore:
    def test_create_returns_session(self, store):
        session = store.create()
        assert isinstance(session, Session)

    def test_load_returns_created_session(self, store):
        session = store.create()
        loaded = store.load(session.id)
        assert loaded.id == session.id

    def test_load_raises_on_missing(self, store):
        with pytest.raises(KeyError):
            store.load("nonexistent")

    def test_append_message_to_session(self, store):
        session = store.create()
        msg = Message(role="user", content="hello")
        store.append_message(session.id, msg)

        messages = store.get_messages(session.id)
        assert len(messages) == 1
        assert messages[0].content == "hello"
        assert messages[0].role == "user"

    def test_messages_are_ordered(self, store):
        session = store.create()
        store.append_message(session.id, Message(role="user", content="first"))
        store.append_message(session.id, Message(role="assistant", content="second"))

        messages = store.get_messages(session.id)
        assert messages[0].content == "first"
        assert messages[1].content == "second"

    def test_list_sessions(self, store):
        store = SessionStore()
        s1 = store.create()
        s2 = store.create()
        ids = {s.id for s in store.list_all()}
        assert s1.id in ids
        assert s2.id in ids

    def test_delete_removes_session(self):
        store = SessionStore()
        session = store.create()
        store.delete(session.id)
        assert len(store.list_all()) == 0

    def test_save_persists_messages(self):
        store = SessionStore()
        session = store.create()
        session.append(Message(role="user", content="hi"))
        store.save(session)
        loaded = store.load(session.id)
        assert loaded.message_count == 1
