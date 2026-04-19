"""Tests for Suggestion Feedback Loop (Improvement #5)."""

from __future__ import annotations

import pytest

from birkin.core.workflow.recommender import WorkflowRecommender
from birkin.memory.event_store import EventStore
from birkin.memory.events import RawEvent
from birkin.memory.wiki import WikiMemory

# -- helpers ----------------------------------------------------------------


def _make_store(tmp_path) -> EventStore:
    return EventStore(db_path=tmp_path / "test_events.db")


def _make_wiki(tmp_path) -> WikiMemory:
    wiki = WikiMemory(root=tmp_path / "memory")
    wiki.init()
    return wiki


def _tool_event(name: str) -> RawEvent:
    return RawEvent(session_id="s1", event_type="tool_call", payload={"name": name})


# -- record_feedback -------------------------------------------------------


class TestRecordFeedback:
    def test_saves_to_wiki(self, tmp_path):
        store = _make_store(tmp_path)
        wiki = _make_wiki(tmp_path)
        rec = WorkflowRecommender(event_store=store, wiki=wiki)

        rec.record_feedback("abc123", "dismissed")

        content = wiki.get_page("meta", "feedback-abc123")
        assert content is not None
        assert '"dismissed"' in content
        assert '"abc123"' in content

    def test_invalid_action_raises(self, tmp_path):
        store = _make_store(tmp_path)
        wiki = _make_wiki(tmp_path)
        rec = WorkflowRecommender(event_store=store, wiki=wiki)

        with pytest.raises(ValueError, match="Invalid action"):
            rec.record_feedback("abc", "invalid_action")

    def test_dismissed_added_to_cache(self, tmp_path):
        store = _make_store(tmp_path)
        wiki = _make_wiki(tmp_path)
        rec = WorkflowRecommender(event_store=store, wiki=wiki)

        rec.record_feedback("xyz789", "dismissed")
        assert "xyz789" in rec._dismissed_ids


# -- _load_dismissed -------------------------------------------------------


class TestLoadDismissed:
    def test_loads_dismissed_from_wiki(self, tmp_path):
        store = _make_store(tmp_path)
        wiki = _make_wiki(tmp_path)
        rec = WorkflowRecommender(event_store=store, wiki=wiki)

        rec.record_feedback("id1", "dismissed")
        rec.record_feedback("id2", "accepted")
        rec.record_feedback("id3", "deleted_after_use")

        # Create a fresh recommender to test loading from wiki
        rec2 = WorkflowRecommender(event_store=store, wiki=wiki)
        dismissed = rec2._load_dismissed()
        assert "id1" in dismissed
        assert "id3" in dismissed
        assert "id2" not in dismissed

    def test_empty_wiki_returns_empty_set(self, tmp_path):
        store = _make_store(tmp_path)
        wiki = _make_wiki(tmp_path)
        rec = WorkflowRecommender(event_store=store, wiki=wiki)
        assert rec._load_dismissed() == set()


# -- suggest with feedback --------------------------------------------------


class TestSuggestWithFeedback:
    @pytest.mark.asyncio
    async def test_dismissed_excluded_from_suggestions(self, tmp_path):
        store = _make_store(tmp_path)
        wiki = _make_wiki(tmp_path)

        for _ in range(5):
            store.append(_tool_event("summarize"))

        rec = WorkflowRecommender(event_store=store, wiki=wiki)
        suggestions = await rec.suggest(top_k=5)
        assert len(suggestions) >= 1

        # Dismiss the suggestion
        for s in suggestions:
            rec.record_feedback(s.id, "dismissed")

        # Now suggest again — dismissed should be excluded
        filtered = await rec.suggest(top_k=5)
        assert len(filtered) == 0

    @pytest.mark.asyncio
    async def test_accepted_lowers_score(self, tmp_path):
        store = _make_store(tmp_path)
        wiki = _make_wiki(tmp_path)

        for _ in range(5):
            store.append(_tool_event("summarize"))

        rec = WorkflowRecommender(event_store=store, wiki=wiki)
        before = await rec.suggest(top_k=5)
        assert len(before) >= 1
        original_score = before[0].confidence

        rec.record_feedback(before[0].id, "accepted")
        after = await rec.suggest(top_k=5)
        accepted_match = [s for s in after if s.id == before[0].id]
        if accepted_match:
            assert accepted_match[0].confidence < original_score
