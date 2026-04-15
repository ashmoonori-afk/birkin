"""Tests for the wiki memory API routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from birkin.core.session import SessionStore
from birkin.gateway.app import create_app
from birkin.gateway.deps import (
    reset_session_store,
    reset_wiki_memory,
    set_session_store,
    set_wiki_memory,
)
from birkin.memory.wiki import WikiMemory


@pytest.fixture(autouse=True)
def _clean_deps(tmp_path):
    """Inject fresh session store and wiki memory for each test."""
    db_file = tmp_path / "test_sessions.db"
    set_session_store(SessionStore(db_path=db_file))

    wiki_dir = tmp_path / "wiki_memory"
    wiki = WikiMemory(root=wiki_dir)
    wiki.init()
    set_wiki_memory(wiki)

    yield

    reset_wiki_memory()
    reset_session_store()


@pytest.fixture()
def client(_clean_deps):
    app = create_app()
    return TestClient(app)


# -- List pages (empty) --


class TestWikiListEmpty:
    def test_list_pages_empty(self, client: TestClient):
        resp = client.get("/api/wiki/pages")
        assert resp.status_code == 200
        assert resp.json() == []


# -- CRUD cycle --


class TestWikiCRUD:
    def test_create_page(self, client: TestClient):
        resp = client.put(
            "/api/wiki/pages/entities/test-page",
            json={"content": "# Test Page\n\nHello world."},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_read_created_page(self, client: TestClient):
        client.put(
            "/api/wiki/pages/entities/test-page",
            json={"content": "# Test Page\n\nHello world."},
        )
        resp = client.get("/api/wiki/pages/entities/test-page")
        assert resp.status_code == 200
        body = resp.json()
        assert body["category"] == "entities"
        assert body["slug"] == "test-page"
        assert "Hello world" in body["content"]

    def test_list_shows_created_page(self, client: TestClient):
        client.put(
            "/api/wiki/pages/entities/test-page",
            json={"content": "# Test Page\n\nSome content."},
        )
        resp = client.get("/api/wiki/pages")
        assert resp.status_code == 200
        pages = resp.json()
        assert len(pages) >= 1
        slugs = [p["slug"] for p in pages]
        assert "test-page" in slugs

    def test_delete_page(self, client: TestClient):
        client.put(
            "/api/wiki/pages/entities/test-page",
            json={"content": "# Test Page"},
        )
        resp = client.delete("/api/wiki/pages/entities/test-page")
        assert resp.status_code == 204

        # Verify page is gone
        resp = client.get("/api/wiki/pages/entities/test-page")
        assert resp.status_code == 404


# -- 404 for nonexistent --


class TestWikiNotFound:
    def test_get_nonexistent_page(self, client: TestClient):
        resp = client.get("/api/wiki/pages/entities/nonexistent")
        assert resp.status_code == 404


# -- Search --


class TestWikiSearch:
    def test_search_finds_page(self, client: TestClient):
        client.put(
            "/api/wiki/pages/entities/test-page",
            json={"content": "# Test Page\n\nSearchable content here."},
        )
        resp = client.get("/api/wiki/search", params={"q": "Searchable"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert results[0]["slug"] == "test-page"

    def test_search_empty_query(self, client: TestClient):
        resp = client.get("/api/wiki/search", params={"q": ""})
        assert resp.status_code == 200
        assert resp.json() == []


# -- Graph --


class TestWikiGraph:
    def test_graph_structure(self, client: TestClient):
        resp = client.get("/api/wiki/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        assert "edges" in body

    def test_graph_with_pages(self, client: TestClient):
        client.put(
            "/api/wiki/pages/entities/page-a",
            json={"content": "# Page A\n\nLinks to [[page-b]]."},
        )
        client.put(
            "/api/wiki/pages/entities/page-b",
            json={"content": "# Page B\n\nStandalone."},
        )
        resp = client.get("/api/wiki/graph")
        assert resp.status_code == 200
        body = resp.json()
        slugs = [n["slug"] for n in body["nodes"]]
        assert "page-a" in slugs
        assert "page-b" in slugs
        assert len(body["edges"]) >= 1


# -- Lint --


class TestWikiLint:
    def test_lint_returns_warnings_list(self, client: TestClient):
        resp = client.get("/api/wiki/lint")
        assert resp.status_code == 200
        body = resp.json()
        assert "warnings" in body
        assert isinstance(body["warnings"], list)

    def test_lint_detects_broken_link(self, client: TestClient):
        client.put(
            "/api/wiki/pages/entities/page-with-broken-link",
            json={"content": "# Page\n\nSee [[nonexistent-target]]."},
        )
        resp = client.get("/api/wiki/lint")
        assert resp.status_code == 200
        warnings = resp.json()["warnings"]
        broken = [w for w in warnings if "nonexistent-target" in w]
        assert len(broken) >= 1
