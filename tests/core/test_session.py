"""Tests for session persistence."""

from birkin.core.providers.base import Message
from birkin.core.session import Session, SessionStore


class TestSession:
    def test_creates_with_unique_id(self):
        s1 = Session()
        s2 = Session()
        assert s1.id != s2.id

    def test_message_count_starts_at_zero(self):
        s = Session()
        assert s.message_count == 0

    def test_append_increments_count(self):
        s = Session()
        s.append(Message(role="user", content="hello"))
        assert s.message_count == 1

    def test_messages_are_ordered(self):
        s = Session()
        s.append(Message(role="user", content="first"))
        s.append(Message(role="assistant", content="second"))
        assert s.messages[0].content == "first"
        assert s.messages[1].content == "second"


class TestSessionStore:
    def test_create_returns_session(self):
        store = SessionStore()
        session = store.create()
        assert isinstance(session, Session)

    def test_load_returns_created_session(self):
        store = SessionStore()
        session = store.create()
        loaded = store.load(session.id)
        assert loaded.id == session.id

    def test_load_raises_on_missing(self):
        store = SessionStore()
        try:
            store.load("nonexistent")
            assert False, "Expected KeyError"
        except KeyError:
            pass

    def test_list_all_returns_created_sessions(self):
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
