"""Tests for S7 UX & Intelligence — command bar, session fork, dashboard, NL builder, insights."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from birkin.core.command.parser import CommandParser, Intent
from birkin.core.command.router import CommandResult, CommandRouter
from birkin.core.workflow.nl_builder import NLWorkflowBuilder, WorkflowDraft
from birkin.memory.event_store import EventStore
from birkin.memory.events import RawEvent, TokenUsageRecord
from birkin.memory.insights.engine import InsightsEngine

# ---------------------------------------------------------------------------
# Command Bar
# ---------------------------------------------------------------------------


class TestCommandParser:
    def test_parse_run_workflow(self) -> None:
        parser = CommandParser()
        intent = parser.parse("run workflow weekly review")
        assert intent.kind == "run_workflow"
        assert "weekly review" in (intent.target or "")

    def test_parse_schedule(self) -> None:
        parser = CommandParser()
        intent = parser.parse("schedule every day at 9am")
        assert intent.kind == "schedule"

    def test_parse_search(self) -> None:
        parser = CommandParser()
        intent = parser.parse("search for API documentation")
        assert intent.kind == "search"

    def test_parse_recall(self) -> None:
        parser = CommandParser()
        intent = parser.parse("what did we discuss about authentication?")
        assert intent.kind == "recall"

    def test_parse_configure(self) -> None:
        parser = CommandParser()
        intent = parser.parse("set provider to anthropic")
        assert intent.kind == "configure"

    def test_parse_unknown_defaults_to_ask(self) -> None:
        parser = CommandParser()
        intent = parser.parse("hello world")
        assert intent.kind == "ask_agent"
        assert intent.confidence == 0.5

    def test_parse_empty(self) -> None:
        parser = CommandParser()
        intent = parser.parse("")
        assert intent.kind == "unknown"

    def test_parse_korean(self) -> None:
        parser = CommandParser()
        intent = parser.parse("매일 요약 보내줘")
        assert intent.kind == "schedule"


class TestCommandRouter:
    @pytest.mark.asyncio
    async def test_dispatch_registered(self) -> None:
        router = CommandRouter()

        async def handle_search(intent: Intent) -> CommandResult:
            return CommandResult(success=True, output=f"Found: {intent.target}")

        router.register("search", handle_search)
        intent = Intent(kind="search", target="API docs")
        result = await router.dispatch(intent)
        assert result.success is True
        assert "API docs" in result.output

    @pytest.mark.asyncio
    async def test_dispatch_unregistered(self) -> None:
        router = CommandRouter()
        intent = Intent(kind="unknown")
        result = await router.dispatch(intent)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_dispatch_fallback(self) -> None:
        router = CommandRouter()

        async def fallback(intent: Intent) -> CommandResult:
            return CommandResult(success=True, output="Fallback response")

        router.register("ask_agent", fallback)
        intent = Intent(kind="unknown")
        result = await router.dispatch(intent)
        assert result.success is True
        assert "Fallback" in result.output

    def test_registered_kinds(self) -> None:
        router = CommandRouter()
        router.register("search", AsyncMock())
        router.register("recall", AsyncMock())
        assert set(router.registered_kinds) == {"search", "recall"}


# ---------------------------------------------------------------------------
# NL Workflow Builder
# ---------------------------------------------------------------------------


class TestNLWorkflowBuilder:
    def test_simple_workflow(self) -> None:
        builder = NLWorkflowBuilder()
        draft = builder.generate("summarize the document and send to telegram")
        assert isinstance(draft, WorkflowDraft)
        assert len(draft.steps) >= 2
        types = [s.node_type for s in draft.steps]
        assert "llm_call" in types
        assert "notify" in types

    def test_scheduled_workflow(self) -> None:
        builder = NLWorkflowBuilder()
        draft = builder.generate("every day, summarize calendar and notify me")
        assert draft.trigger is not None
        assert draft.trigger["type"] == "cron"
        assert len(draft.review_notes) > 0

    def test_single_step(self) -> None:
        builder = NLWorkflowBuilder()
        draft = builder.generate("analyze this data")
        assert len(draft.steps) == 1
        assert draft.steps[0].node_type == "llm_call"

    def test_search_step(self) -> None:
        builder = NLWorkflowBuilder()
        draft = builder.generate("search for latest news and summarize")
        types = [s.node_type for s in draft.steps]
        assert "tool_call" in types

    def test_to_graph_json(self) -> None:
        builder = NLWorkflowBuilder()
        draft = builder.generate("analyze data and send report")
        graph = draft.to_graph_json()
        assert "nodes" in graph
        assert "edges" in graph
        assert graph["mode"] == "graph"

    def test_korean_input(self) -> None:
        builder = NLWorkflowBuilder()
        draft = builder.generate("매일, 뉴스 검색해서 요약해줘")
        assert draft.trigger is not None  # "매일" triggers schedule
        assert len(draft.steps) >= 1


# ---------------------------------------------------------------------------
# Insights Engine
# ---------------------------------------------------------------------------


class TestInsightsEngine:
    def _seed_events(self, store: EventStore) -> None:
        """Seed test events."""
        for i in range(10):
            store.append(
                RawEvent(
                    session_id=f"s{i % 3}",
                    event_type="llm_call",
                    provider="anthropic" if i % 2 == 0 else "openai",
                    timestamp=f"2026-04-16T{10 + i}:00:00Z",
                    tokens=TokenUsageRecord(tokens_in=100, tokens_out=200, cost_usd=0.01),
                )
            )
        for i in range(5):
            store.append(
                RawEvent(
                    session_id="s0",
                    event_type="tool_call",
                    timestamp=f"2026-04-16T{10 + i}:30:00Z",
                    payload={"name": "web_search" if i % 2 == 0 else "file_read"},
                )
            )

    def test_weekly_digest(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        self._seed_events(store)
        engine = InsightsEngine(store)

        digest = engine.weekly_digest("2026-04-14", "2026-04-20")
        assert digest.total_events == 15
        assert digest.total_sessions >= 1
        assert digest.total_tokens > 0
        assert "anthropic" in digest.providers_used or "openai" in digest.providers_used
        assert len(digest.summary) > 0
        store.close()

    def test_weekly_digest_empty(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        engine = InsightsEngine(store)
        digest = engine.weekly_digest("2025-01-01", "2025-01-07")
        assert digest.total_events == 0
        store.close()

    def test_identify_patterns(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        self._seed_events(store)
        engine = InsightsEngine(store)

        patterns = engine.identify_patterns(days=30)
        assert len(patterns) >= 1
        names = [p.name for p in patterns]
        assert any("provider" in n.lower() for n in names)
        store.close()

    def test_usage_trend(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        self._seed_events(store)
        engine = InsightsEngine(store)

        trend = engine.usage_trend(days=3)
        assert len(trend) == 3
        assert all("date" in day and "tokens" in day for day in trend)
        store.close()


# ---------------------------------------------------------------------------
# Dashboard aggregator import
# ---------------------------------------------------------------------------


class TestDashboardAPI:
    def test_aggregator_import(self) -> None:
        from birkin.gateway.observability.aggregator import (
            ErrorSummary,
            LatencyStats,
            SpendReport,
        )

        assert SpendReport is not None
        assert LatencyStats is not None
        assert ErrorSummary is not None

    def test_observability_router_import(self) -> None:
        from birkin.gateway.routers.observability import router

        assert router.prefix == "/api/observability"
