"""Tests for Proactive Workflow Discovery (Improvement #2)."""

from __future__ import annotations

import pytest

from birkin.core.workflow.recommender import WorkflowRecommender
from birkin.memory.event_store import EventStore
from birkin.memory.events import RawEvent

# -- helpers ----------------------------------------------------------------


def _make_store(tmp_path) -> EventStore:
    return EventStore(db_path=tmp_path / "test_events.db")


def _tool_event(name: str) -> RawEvent:
    return RawEvent(session_id="s1", event_type="tool_call", payload={"name": name})


# -- tests ------------------------------------------------------------------


class TestCheckAndNotify:
    @pytest.mark.asyncio
    async def test_returns_suggestions_when_patterns_exist(self, tmp_path):
        store = _make_store(tmp_path)
        for _ in range(5):
            store.append(_tool_event("web_search"))

        rec = WorkflowRecommender(event_store=store)
        results = await rec.check_and_notify()
        assert len(results) >= 1
        assert all(s.confidence > 0.7 for s in results)

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_patterns(self, tmp_path):
        store = _make_store(tmp_path)
        rec = WorkflowRecommender(event_store=store)
        results = await rec.check_and_notify()
        assert results == []

    @pytest.mark.asyncio
    async def test_filters_low_confidence(self, tmp_path):
        store = _make_store(tmp_path)
        # Only 3 events — just at threshold, low confidence
        for _ in range(3):
            store.append(_tool_event("rare_tool"))

        rec = WorkflowRecommender(event_store=store)
        all_suggestions = await rec.suggest(top_k=10)
        notified = await rec.check_and_notify()
        # check_and_notify filters to confidence > 0.7
        assert len(notified) <= len(all_suggestions)


class TestChatResponseSuggestions:
    def test_schema_includes_suggestions_field(self):
        from birkin.gateway.schemas import ChatResponse

        resp = ChatResponse(session_id="s1", reply="hi")
        assert resp.suggestions == []
        assert "suggestions" in resp.model_dump()

    def test_schema_with_suggestions(self):
        from birkin.gateway.schemas import ChatResponse

        resp = ChatResponse(
            session_id="s1",
            reply="hi",
            suggestions=[{"title": "Auto web search", "confidence": 0.9}],
        )
        assert len(resp.suggestions) == 1
