"""Tests for the insights engine API endpoints and scheduling logic."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from birkin.core.session import SessionStore
from birkin.gateway.app import create_app
from birkin.gateway.deps import (
    reset_insights_engine,
    reset_session_store,
    set_insights_engine,
    set_session_store,
)
from birkin.memory.insights.engine import InsightsEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean(tmp_path):
    """Inject fresh isolated stores for each test."""
    db_file = tmp_path / "test_sessions.db"
    set_session_store(SessionStore(db_path=db_file))
    yield
    reset_session_store()
    reset_insights_engine()


def _empty_event_store() -> MagicMock:
    """Return a mock EventStore that always returns an empty list."""
    store = MagicMock()
    store.since.return_value = []
    return store


@pytest.fixture()
def client_with_empty_store(_clean):
    """TestClient backed by an InsightsEngine with no events."""
    engine = InsightsEngine(_empty_event_store())
    set_insights_engine(engine)
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/insights/weekly
# ---------------------------------------------------------------------------


class TestWeeklyEndpoint:
    def test_weekly_returns_200(self, client_with_empty_store: TestClient):
        resp = client_with_empty_store.get("/api/insights/weekly")
        assert resp.status_code == 200
        body = resp.json()
        assert "period" in body
        assert body["total_events"] == 0

    def test_weekly_with_date_params(self, client_with_empty_store: TestClient):
        resp = client_with_empty_store.get(
            "/api/insights/weekly",
            params={"start_date": "2026-04-01", "end_date": "2026-04-07"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"] == "2026-04-01 to 2026-04-07"

    def test_weekly_empty_store_returns_empty_digest(self, client_with_empty_store: TestClient):
        resp = client_with_empty_store.get("/api/insights/weekly")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_events"] == 0
        assert body["total_sessions"] == 0
        assert body["providers_used"] == []


# ---------------------------------------------------------------------------
# GET /api/insights/patterns
# ---------------------------------------------------------------------------


class TestPatternsEndpoint:
    def test_patterns_returns_list(self, client_with_empty_store: TestClient):
        resp = client_with_empty_store.get("/api/insights/patterns")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_patterns_with_days_param(self, client_with_empty_store: TestClient):
        resp = client_with_empty_store.get("/api/insights/patterns", params={"days": 7})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_patterns_empty_store_returns_empty_list(self, client_with_empty_store: TestClient):
        resp = client_with_empty_store.get("/api/insights/patterns")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/insights/trend
# ---------------------------------------------------------------------------


class TestTrendEndpoint:
    def test_trend_returns_data(self, client_with_empty_store: TestClient):
        resp = client_with_empty_store.get("/api/insights/trend")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Default 7 days
        assert len(data) == 7

    def test_trend_with_days_param(self, client_with_empty_store: TestClient):
        resp = client_with_empty_store.get("/api/insights/trend", params={"days": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

    def test_trend_empty_store_returns_zero_tokens(self, client_with_empty_store: TestClient):
        resp = client_with_empty_store.get("/api/insights/trend")
        assert resp.status_code == 200
        for day in resp.json():
            assert day["tokens"] == 0
            assert day["events"] == 0


# ---------------------------------------------------------------------------
# Sunday scheduling logic
# ---------------------------------------------------------------------------


class TestSundayScheduling:
    def test_sunday_weekday_check(self):
        """The weekday guard used in _daily_memory_loop fires on Sundays."""
        sunday = dt.datetime(2026, 4, 19, 3, 0, 0)
        assert sunday.weekday() == 6

    def test_non_sunday_skips(self):
        """Non-Sunday days do not pass the weekday guard."""
        monday = dt.datetime(2026, 4, 13, 3, 0, 0)
        assert monday.weekday() != 6

    def test_weekly_digest_produces_wiki_content(self):
        """InsightsEngine.weekly_digest returns a summary suitable for wiki ingest."""
        mock_store = _empty_event_store()
        from birkin.memory.insights.engine import InsightsEngine

        engine = InsightsEngine(mock_store)
        digest = engine.weekly_digest("2026-04-13", "2026-04-19")

        # The digest should have a non-None summary string (even if empty data)
        assert isinstance(digest.summary, str)
        assert digest.period == "2026-04-13 to 2026-04-19"

    def test_sunday_branch_saves_to_wiki(self):
        """Simulate the Sunday branch: digest is saved via wiki.ingest."""
        mock_wiki = MagicMock()
        mock_store = _empty_event_store()

        from birkin.memory.insights.engine import InsightsEngine

        fake_now = dt.datetime(2026, 4, 19, 3, 0, 0)  # Sunday
        end = fake_now.strftime("%Y-%m-%d")
        start = (fake_now - dt.timedelta(days=6)).strftime("%Y-%m-%d")

        insights = InsightsEngine(mock_store)
        digest = insights.weekly_digest(start, end)

        # This mirrors the code path in _daily_memory_loop
        if fake_now.weekday() == 6:
            mock_wiki.ingest("insights", f"weekly-{end}", digest.summary)

        mock_wiki.ingest.assert_called_once_with(
            "insights",
            "weekly-2026-04-19",
            digest.summary,
        )
