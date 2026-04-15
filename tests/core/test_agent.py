"""Tests for Agent class."""

from __future__ import annotations

import pytest

from birkin.core.agent import Agent
from birkin.core.session import SessionStore
from tests.fakes import FakeProvider


@pytest.fixture
def session_store():
    """Provide a temporary SessionStore."""
    return SessionStore(":memory:")


class TestAgent:
    def test_chat_returns_provider_reply(self, session_store):
        provider = FakeProvider(reply="hello back")
        agent = Agent(provider=provider, session_store=session_store)
        result = agent.chat("hi")
        assert result == "hello back"

    def test_chat_appends_to_session(self, session_store):
        provider = FakeProvider()
        agent = Agent(provider=provider, session_store=session_store)
        agent.chat("first")
        # User + assistant = 2 messages
        count = session_store.get_message_count(agent.session_id)
        assert count == 2

    def test_system_prompt_prepended(self, session_store):
        provider = FakeProvider()
        agent = Agent(provider=provider, session_store=session_store, system_prompt="Be brief.")
        agent.chat("test")
        assert provider.last_messages[0].role == "system"
        assert provider.last_messages[0].content == "Be brief."

    def test_loads_existing_session(self, session_store):
        provider = FakeProvider()

        # Create first agent and chat
        agent1 = Agent(provider=provider, session_store=session_store)
        session_id = agent1.session_id
        agent1.chat("first")

        # Create second agent with same session
        agent2 = Agent(provider=provider, session_store=session_store, session_id=session_id)
        agent2.chat("now")

        # Should have 4 messages: 2 from first chat, 2 from second
        count = session_store.get_message_count(session_id)
        assert count == 4

    def test_default_system_prompt(self, session_store):
        provider = FakeProvider()
        agent = Agent(provider=provider, session_store=session_store)
        agent.chat("test")
        assert "Birkin" in provider.last_messages[0].content


class TestPickCategory:
    def test_entity_signals(self):
        assert Agent._pick_category("who is the CEO of the company", "The CEO is...") == "entities"

    def test_concept_signals(self):
        assert Agent._pick_category("how to implement the pattern", "The design pattern...") == "concepts"

    def test_default_sessions(self):
        assert Agent._pick_category("hello there", "hi!") == "sessions"

    def test_entity_needs_two_signals(self):
        # Only one signal should not trigger entity
        assert Agent._pick_category("company overview", "plain reply") == "sessions"

    def test_concept_needs_two_signals(self):
        # Only one signal should not trigger concept
        assert Agent._pick_category("pattern", "ok") == "sessions"


class TestMakeSlug:
    def test_meaningful_words(self):
        slug = Agent._make_slug("How to build a REST API", "abc123")
        assert slug.startswith("how-build-rest-api")
        assert "abc123" in slug

    def test_strips_stopwords(self):
        slug = Agent._make_slug("the best way to do it", "xyz789")
        assert "the" not in slug.split("-")[:4]

    def test_fallback_for_empty(self):
        slug = Agent._make_slug("", "sess01")
        assert slug.startswith("chat-")

    def test_special_characters_removed(self):
        slug = Agent._make_slug("What is @user's project?", "aaa111")
        assert "@" not in slug
        assert "'" not in slug
