"""Unit tests for WorkflowRecommender."""

from __future__ import annotations

import datetime as dt

import pytest

from birkin.core.workflow.recommender import (
    RepetitionSignal,
    WorkflowRecommender,
    WorkflowSuggestion,
)
from birkin.memory.event_store import EventStore
from birkin.memory.events import RawEvent

# -- helpers ----------------------------------------------------------------


def _make_store(tmp_path) -> EventStore:
    return EventStore(db_path=tmp_path / "test_events.db")


def _tool_event(name: str, session: str = "s1") -> RawEvent:
    return RawEvent(
        session_id=session,
        event_type="tool_call",
        payload={"name": name},
    )


def _user_msg(content: str, session: str = "s1") -> RawEvent:
    return RawEvent(
        session_id=session,
        event_type="user_message",
        payload={"content": content},
    )


# -- detect_repetitions -----------------------------------------------------


class TestDetectRepetitions:
    @pytest.mark.asyncio
    async def test_finds_frequent_tool_calls(self, tmp_path):
        store = _make_store(tmp_path)
        for _ in range(5):
            store.append(_tool_event("web_search"))

        rec = WorkflowRecommender(event_store=store)
        signals = await rec.detect_repetitions(days=30)

        tool_signals = [s for s in signals if s.pattern_type == "tool_repeat"]
        assert len(tool_signals) >= 1
        assert tool_signals[0].frequency == 5
        assert "web_search" in tool_signals[0].description

    @pytest.mark.asyncio
    async def test_ignores_infrequent_tools(self, tmp_path):
        store = _make_store(tmp_path)
        store.append(_tool_event("rare_tool"))

        rec = WorkflowRecommender(event_store=store)
        signals = await rec.detect_repetitions(days=30)

        tool_signals = [s for s in signals if s.pattern_type == "tool_repeat"]
        assert len(tool_signals) == 0

    @pytest.mark.asyncio
    async def test_detects_topic_repetitions(self, tmp_path):
        store = _make_store(tmp_path)
        for _ in range(6):
            store.append(_user_msg("market analysis report for tomorrow"))

        rec = WorkflowRecommender(event_store=store)
        signals = await rec.detect_repetitions(days=30)

        topic_signals = [s for s in signals if s.pattern_type == "topic_repeat"]
        assert len(topic_signals) >= 1


# -- suggest ----------------------------------------------------------------


class TestSuggest:
    @pytest.mark.asyncio
    async def test_returns_scored_suggestions(self, tmp_path):
        store = _make_store(tmp_path)
        for _ in range(5):
            store.append(_tool_event("summarize"))
        for _ in range(3):
            store.append(_tool_event("translate"))

        rec = WorkflowRecommender(event_store=store)
        suggestions = await rec.suggest(top_k=5)

        assert len(suggestions) >= 1
        assert all(isinstance(s, WorkflowSuggestion) for s in suggestions)
        # sorted by confidence descending
        confs = [s.confidence for s in suggestions]
        assert confs == sorted(confs, reverse=True)

    @pytest.mark.asyncio
    async def test_filters_dismissed(self, tmp_path):
        store = _make_store(tmp_path)
        for _ in range(5):
            store.append(_tool_event("summarize"))

        rec = WorkflowRecommender(event_store=store)
        suggestions = await rec.suggest(top_k=5)
        assert len(suggestions) >= 1

        # dismiss all suggestion IDs
        for s in suggestions:
            rec._dismissed_ids.add(s.id)

        filtered = await rec.suggest(top_k=5)
        assert len(filtered) == 0

    @pytest.mark.asyncio
    async def test_empty_history_returns_empty(self, tmp_path):
        store = _make_store(tmp_path)
        rec = WorkflowRecommender(event_store=store)
        suggestions = await rec.suggest()
        assert suggestions == []


# -- scoring ----------------------------------------------------------------


class TestScoring:
    def test_tool_repeat_scores_higher_than_topic(self):
        rec = WorkflowRecommender(event_store=EventStore(":memory:"))
        now = dt.datetime.now(dt.timezone.utc).isoformat()

        tool_sig = RepetitionSignal(
            pattern_type="tool_repeat",
            description="Tool 'x' called 5 times",
            frequency=5,
            last_seen=now,
        )
        topic_sig = RepetitionSignal(
            pattern_type="topic_repeat",
            description="Topic 'y' mentioned 5 times",
            frequency=5,
            last_seen=now,
        )

        tool_score = rec._score_suggestion(tool_sig)
        topic_score = rec._score_suggestion(topic_sig)
        assert tool_score > topic_score

    def test_dismissed_feedback_zeroes_score(self):
        rec = WorkflowRecommender(event_store=EventStore(":memory:"))
        sig = RepetitionSignal(
            pattern_type="tool_repeat",
            description="test",
            frequency=10,
            last_seen=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        score = rec._score_suggestion(sig, feedback_action="dismissed")
        assert score == 0.0
