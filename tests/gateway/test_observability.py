"""Tests for the observability hero metrics endpoint."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from birkin.gateway.app import create_app
from birkin.gateway.routers.observability import set_wiki
from birkin.memory.wiki import WikiMemory


@pytest.fixture()
def wiki(tmp_path):
    """Create a fresh WikiMemory in a temp directory."""
    w = WikiMemory(tmp_path / "mem")
    w.init()
    return w


@pytest.fixture()
def client(wiki):
    set_wiki(wiki)
    app = create_app()
    yield TestClient(app)
    set_wiki(None)  # type: ignore[arg-type]


class TestHeroReturnsStructure:
    """GET /api/observability/hero returns all 4 keys with int types."""

    def test_hero_returns_structure(self, client: TestClient) -> None:
        resp = client.get("/api/observability/hero")
        assert resp.status_code == 200
        body = resp.json()
        expected_keys = {
            "tokens_saved_this_week",
            "automations_run",
            "memory_pages_total",
            "memory_pages_delta_week",
        }
        assert set(body.keys()) == expected_keys
        for key in expected_keys:
            assert isinstance(body[key], int), f"{key} should be int, got {type(body[key])}"


class TestHeroZeroWhenEmpty:
    """Fresh install returns zeros for all hero metrics."""

    def test_hero_zero_when_empty(self, client: TestClient) -> None:
        resp = client.get("/api/observability/hero")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tokens_saved_this_week"] == 0
        assert body["automations_run"] == 0
        assert body["memory_pages_total"] == 0
        assert body["memory_pages_delta_week"] == 0


class TestHeroMemoryCount:
    """Creating wiki pages updates the hero memory counts."""

    def test_hero_memory_count(self, wiki: WikiMemory, client: TestClient) -> None:
        wiki.ingest("entities", "test-page-1", "# Page 1\nContent here.")
        wiki.ingest("concepts", "test-page-2", "# Page 2\nMore content.")
        wiki.ingest("sessions", "test-page-3", "# Page 3\nSession notes.")

        resp = client.get("/api/observability/hero")
        assert resp.status_code == 200
        body = resp.json()
        assert body["memory_pages_total"] == 3
        # All pages were just created, so delta should be 3
        assert body["memory_pages_delta_week"] == 3


class TestHeroMemoryDelta:
    """pages_created_since respects the time window."""

    def test_pages_created_since(self, wiki: WikiMemory) -> None:
        wiki.ingest("entities", "recent-page", "# Recent")
        # All pages created just now should count
        now = dt.datetime.now(dt.timezone.utc)
        week_ago = now - dt.timedelta(days=7)
        assert wiki.pages_created_since(week_ago) == 1
        # Far future cutoff should return 0
        future = now + dt.timedelta(days=1)
        assert wiki.pages_created_since(future) == 0


class TestPageCount:
    """page_count returns correct count."""

    def test_page_count_empty(self, wiki: WikiMemory) -> None:
        assert wiki.page_count() == 0

    def test_page_count_after_ingest(self, wiki: WikiMemory) -> None:
        wiki.ingest("entities", "a", "# A")
        wiki.ingest("entities", "b", "# B")
        assert wiki.page_count() == 2
