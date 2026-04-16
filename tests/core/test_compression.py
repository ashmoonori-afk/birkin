"""Unit tests for birkin.core.compression."""

from __future__ import annotations

import pytest

from birkin.core import compression
from birkin.core.compression import (
    _build_transcript,
    _cache_key,
    summarize_messages,
    summarize_or_cache,
)
from birkin.core.models import Message
from tests.fakes import FakeProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_messages(*pairs: tuple[str, str]) -> list[Message]:
    """Build a list of Messages from (role, content) pairs."""
    return [Message(role=role, content=content) for role, content in pairs]


# ---------------------------------------------------------------------------
# _cache_key
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_cache_key_deterministic(self) -> None:
        msgs = _make_messages(("user", "hello"), ("assistant", "hi"))
        assert _cache_key(msgs) == _cache_key(msgs)

    def test_cache_key_differs_for_different_messages(self) -> None:
        msgs_a = _make_messages(("user", "hello"))
        msgs_b = _make_messages(("user", "goodbye"))
        assert _cache_key(msgs_a) != _cache_key(msgs_b)


# ---------------------------------------------------------------------------
# _build_transcript
# ---------------------------------------------------------------------------

class TestBuildTranscript:
    def test_build_transcript_formats_correctly(self) -> None:
        msgs = _make_messages(("user", "What is 2+2?"), ("assistant", "4"))
        result = _build_transcript(msgs)
        assert result == "USER: What is 2+2?\nASSISTANT: 4"


# ---------------------------------------------------------------------------
# summarize_messages
# ---------------------------------------------------------------------------

class TestSummarizeMessages:
    def test_summarize_messages_returns_content(self) -> None:
        provider = FakeProvider(reply="A short summary.")
        msgs = _make_messages(("user", "tell me a story"), ("assistant", "once upon a time"))
        result = summarize_messages(msgs, provider)
        assert result == "A short summary."

    def test_summarize_messages_returns_none_on_empty(self) -> None:
        provider = FakeProvider(reply="should not be used")
        result = summarize_messages([], provider)
        assert result is None

    def test_summarize_messages_returns_none_on_error(self) -> None:
        provider = FakeProvider(reply="ignored")
        # Monkey-patch complete to raise
        provider.complete = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[assignment]
        msgs = _make_messages(("user", "hi"))
        result = summarize_messages(msgs, provider)
        assert result is None


# ---------------------------------------------------------------------------
# summarize_or_cache
# ---------------------------------------------------------------------------

class TestSummarizeOrCache:
    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        """Ensure each test starts with a clean summary cache."""
        compression._summary_cache.clear()

    def test_summarize_or_cache_caches_result(self) -> None:
        provider = FakeProvider(reply="cached summary")
        msgs = _make_messages(("user", "hello"), ("assistant", "hi"))

        first = summarize_or_cache(msgs, provider)
        assert first == "cached summary"

        # Replace provider reply; second call should still return cached value
        provider._reply = "new reply that should not appear"
        second = summarize_or_cache(msgs, provider)
        assert second == "cached summary"

    def test_cache_eviction_at_max_size(self) -> None:
        provider = FakeProvider(reply="summary")

        # Fill cache with 128 entries
        for i in range(128):
            msgs = _make_messages(("user", f"message-{i}"))
            summarize_or_cache(msgs, provider)

        assert len(compression._summary_cache) == 128

        # The first key inserted
        first_key = _cache_key(_make_messages(("user", "message-0")))
        assert first_key in compression._summary_cache

        # Insert the 129th entry; oldest (message-0) should be evicted
        msgs_new = _make_messages(("user", "message-128"))
        summarize_or_cache(msgs_new, provider)

        assert len(compression._summary_cache) == 128
        assert first_key not in compression._summary_cache
