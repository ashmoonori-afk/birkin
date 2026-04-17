"""Tests for Agent class."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from birkin.core.agent import (
    _KEEP_HEAD,
    _KEEP_TAIL,
    Agent,
    _executor,
    _run_async,
    shutdown_executor,
)
from birkin.core.models import Message
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

    def test_entity_single_signal(self):
        # Single signal now triggers entity (threshold lowered to 1 for Korean support)
        assert Agent._pick_category("company overview", "plain reply") == "entities"

    def test_concept_single_signal(self):
        # Single signal now triggers concept (threshold lowered to 1 for Korean support)
        assert Agent._pick_category("pattern", "ok") == "concepts"

    def test_korean_entity_signals(self):
        assert Agent._pick_category("이 회사에 대해 알려줘", "삼성전자는...") == "entities"

    def test_korean_concept_signals(self):
        assert Agent._pick_category("트랜스포머 원리 설명해줘", "트랜스포머는...") == "concepts"


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


class TestRunAsync:
    def test_run_async_returns_result(self):
        async def _add():
            return 1 + 2

        assert _run_async(_add()) == 3

    def test_executor_thread_names(self):
        """Verify the shared pool uses 'birkin-tool' prefixed threads."""
        captured: list[str] = []

        def _capture():
            captured.append(threading.current_thread().name)

        future = _executor.submit(_capture)
        future.result()
        assert len(captured) == 1
        assert captured[0].startswith("birkin-tool")

    def test_shutdown_executor_is_callable(self):
        """shutdown_executor can be called without error.

        We call with wait=True on a fresh executor state; the pool stays
        usable for subsequent tests because CPython allows resubmission
        only before shutdown, so we re-initialise the module-level object.
        """
        # Just verify it does not raise.
        shutdown_executor(wait=True)

        # Re-initialise so other tests are not affected.
        from concurrent.futures import ThreadPoolExecutor as _TPE

        import birkin.core.agent as _mod

        _mod._executor = _TPE(max_workers=4, thread_name_prefix="birkin-tool")


def _make_messages(count: int, char_per_msg: int = 10) -> list[Message]:
    """Helper: generate *count* user messages with given content length."""
    return [Message(role="user", content=f"msg-{i} " + "x" * char_per_msg) for i in range(count)]


class TestCompressMessages:
    """Tests for the LLM-based message compression path."""

    def test_short_history_no_compression(self):
        """Messages under the token budget are returned unchanged."""
        msgs = _make_messages(5, char_per_msg=10)
        provider = FakeProvider()
        result = Agent._compress_messages(msgs, provider)
        assert result == msgs

    def test_long_history_uses_summarization(self):
        """When over budget, summarize_or_cache is called and its result
        is inserted as a system message between head and tail."""
        # Each message ~1000 chars => ~250 tokens; 25 msgs => ~6250 tokens.
        # We patch the budget to 1000 so compression triggers.
        msgs = _make_messages(25, char_per_msg=1000)
        summary_text = "User discussed topics A, B, and C."
        provider = FakeProvider(reply=summary_text)

        with patch("birkin.core.agent._CONTEXT_BUDGET_TOKENS", 1000):
            result = Agent._compress_messages(msgs, provider)

        assert len(result) == _KEEP_HEAD + 1 + _KEEP_TAIL
        # Head preserved
        assert result[:_KEEP_HEAD] == msgs[:_KEEP_HEAD]
        # Summary message
        summary_msg = result[_KEEP_HEAD]
        assert summary_msg.role == "system"
        assert "[Summary of earlier conversation]" in summary_msg.content
        assert summary_text in summary_msg.content
        # Tail preserved
        assert result[_KEEP_HEAD + 1 :] == msgs[-_KEEP_TAIL:]

    def test_summarization_failure_falls_back_to_marker(self):
        """When summarize_or_cache returns None, the old marker behavior
        is used as a fallback."""
        msgs = _make_messages(25, char_per_msg=1000)

        with (
            patch("birkin.core.agent._CONTEXT_BUDGET_TOKENS", 1000),
            patch(
                "birkin.core.agent.summarize_or_cache",
                return_value=None,
            ),
        ):
            result = Agent._compress_messages(msgs, FakeProvider())

        assert len(result) == _KEEP_HEAD + 1 + _KEEP_TAIL
        marker = result[_KEEP_HEAD]
        assert marker.role == "system"
        assert marker.content == "[Earlier conversation compressed]"
