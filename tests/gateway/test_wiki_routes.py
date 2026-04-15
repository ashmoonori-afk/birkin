"""Tests for the wiki memory API routes."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from birkin.core.session import SessionStore
from birkin.gateway.app import create_app
from birkin.gateway.deps import (
    get_wiki_memory,
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


# -- Upload --


class TestWikiUpload:
    def test_upload_txt(self, client: TestClient):
        resp = client.post(
            "/api/wiki/upload",
            files={"file": ("notes.txt", b"Hello world content", "text/plain")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["slug"] == "notes"
        assert body["category"] == "concepts"
        assert "Hello world" in body["preview"]

    def test_upload_md(self, client: TestClient):
        resp = client.post(
            "/api/wiki/upload",
            files={"file": ("readme.md", b"# Title\n\nMarkdown body.", "text/markdown")},
        )
        assert resp.status_code == 200
        assert resp.json()["slug"] == "readme"

    def test_upload_csv(self, client: TestClient):
        csv_content = b"name,age\nAlice,30\nBob,25\n"
        resp = client.post(
            "/api/wiki/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "Alice" in body["preview"]
        assert "|" in body["preview"]  # markdown table

    def test_upload_entity_filename(self, client: TestClient):
        resp = client.post(
            "/api/wiki/upload",
            files={"file": ("team-members.txt", b"John, Jane", "text/plain")},
        )
        assert resp.status_code == 200
        assert resp.json()["category"] == "entities"

    def test_upload_unsupported_ext(self, client: TestClient):
        resp = client.post(
            "/api/wiki/upload",
            files={"file": ("image.png", b"\x89PNG", "image/png")},
        )
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]


# -- Auto-Link --


class TestWikiAutoLink:
    def test_auto_link_endpoint(self, client: TestClient):
        client.put("/api/wiki/pages/concepts/python", json={"content": "# Python\n\nA language."})
        client.put("/api/wiki/pages/concepts/fastapi", json={"content": "# FastAPI\n\nBuilt with python."})
        resp = client.post("/api/wiki/auto-link")
        assert resp.status_code == 200
        body = resp.json()
        assert "links_added" in body
        assert body["links_added"] >= 1

    def test_auto_link_no_pages(self, client: TestClient):
        resp = client.post("/api/wiki/auto-link")
        assert resp.status_code == 200
        assert resp.json()["links_added"] == 0


# -- Summarize --


class TestWikiSummarize:
    def test_summarize_old_sessions(self, client: TestClient):
        # Create session pages
        client.put("/api/wiki/pages/sessions/old-chat-1", json={"content": "# Old 1\n\nOld content."})
        client.put("/api/wiki/pages/sessions/old-chat-2", json={"content": "# Old 2\n\nMore old content."})

        # Set file mtimes to 48 hours ago
        wiki = get_wiki_memory()
        for slug in ("old-chat-1", "old-chat-2"):
            path = wiki.wiki_dir / "sessions" / f"{slug}.md"
            old_time = time.time() - 48 * 3600
            os.utime(path, (old_time, old_time))

        resp = client.post("/api/wiki/summarize")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summarized"] == 2
        assert len(body["deleted_slugs"]) == 2

    def test_summarize_no_old_sessions(self, client: TestClient):
        resp = client.post("/api/wiki/summarize")
        assert resp.status_code == 200
        body = resp.json()
        assert body["summarized"] == 0
        assert body["deleted_slugs"] == []
