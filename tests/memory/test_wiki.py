"""Tests for birkin.memory.wiki module."""

from __future__ import annotations

import os
import time

import pytest

from birkin.memory.wiki import WikiMemory


@pytest.fixture
def wiki(tmp_path):
    """Provide a WikiMemory rooted in a temp directory."""
    mem = WikiMemory(tmp_path / "memory")
    mem.init()
    return mem


class TestInit:
    def test_creates_directory_structure(self, wiki):
        assert wiki.wiki_dir.is_dir()
        assert wiki.raw_dir.is_dir()
        assert (wiki.wiki_dir / "entities").is_dir()
        assert (wiki.wiki_dir / "concepts").is_dir()
        assert (wiki.wiki_dir / "sessions").is_dir()

    def test_creates_seed_files(self, wiki):
        assert (wiki.wiki_dir / "index.md").is_file()
        assert (wiki.wiki_dir / "log.md").is_file()
        assert (wiki.root / "schema.md").is_file()

    def test_init_is_idempotent(self, wiki):
        wiki.init()
        wiki.init()
        assert (wiki.wiki_dir / "index.md").is_file()


class TestIngest:
    def test_creates_page(self, wiki):
        path = wiki.ingest("concepts", "asyncio", "# Asyncio\n\nPython async runtime.")
        assert path.is_file()
        assert "Asyncio" in path.read_text()

    def test_updates_index(self, wiki):
        wiki.ingest("entities", "python", "# Python\n\nProgramming language.")
        index = (wiki.wiki_dir / "index.md").read_text()
        assert "python" in index

    def test_appends_log(self, wiki):
        wiki.ingest("entities", "rust", "# Rust\n\nSystems language.")
        log = (wiki.wiki_dir / "log.md").read_text()
        assert "created entities/rust.md" in log

    def test_update_existing_page(self, wiki):
        wiki.ingest("concepts", "tdd", "# TDD\n\nv1")
        wiki.ingest("concepts", "tdd", "# TDD\n\nv2 — updated")
        content = wiki.get_page("concepts", "tdd")
        assert "v2" in content
        log = (wiki.wiki_dir / "log.md").read_text()
        assert "updated concepts/tdd.md" in log


class TestQuery:
    def test_finds_matching_pages(self, wiki):
        wiki.ingest("concepts", "fastapi", "# FastAPI\n\nModern Python web framework.")
        wiki.ingest("concepts", "django", "# Django\n\nBatteries-included Python framework.")
        results = wiki.query("Python")
        assert len(results) == 2

    def test_returns_empty_for_no_match(self, wiki):
        wiki.ingest("concepts", "go", "# Go\n\nSystems programming.")
        results = wiki.query("JavaScript")
        assert results == []

    def test_result_includes_snippet(self, wiki):
        wiki.ingest("entities", "karpathy", "# Andrej Karpathy\n\nAI researcher.")
        results = wiki.query("karpathy")
        assert len(results) == 1
        assert "snippet" in results[0]


class TestGetPage:
    def test_returns_content(self, wiki):
        wiki.ingest("entities", "birkin", "# Birkin\n\nAI agent platform.")
        content = wiki.get_page("entities", "birkin")
        assert "AI agent platform" in content

    def test_returns_none_for_missing(self, wiki):
        assert wiki.get_page("entities", "nonexistent") is None


class TestListPages:
    def test_lists_all_pages(self, wiki):
        wiki.ingest("entities", "a", "# A")
        wiki.ingest("concepts", "b", "# B")
        wiki.ingest("sessions", "c", "# C")
        pages = wiki.list_pages()
        slugs = {p["slug"] for p in pages}
        assert slugs == {"a", "b", "c"}


class TestDeletePage:
    def test_deletes_existing(self, wiki):
        wiki.ingest("entities", "temp", "# Temp")
        assert wiki.delete_page("entities", "temp") is True
        assert wiki.get_page("entities", "temp") is None

    def test_returns_false_for_missing(self, wiki):
        assert wiki.delete_page("entities", "nope") is False


class TestLint:
    def test_detects_broken_wikilinks(self, wiki):
        wiki.ingest("concepts", "a", "See [[nonexistent]] for details.")
        warnings = wiki.lint()
        assert any("broken link" in w for w in warnings)

    def test_detects_orphaned_pages(self, wiki):
        wiki.ingest("concepts", "lonely", "# Lonely\n\nNo one links here.")
        warnings = wiki.lint()
        assert any("orphaned page" in w and "lonely" in w for w in warnings)


class TestBuildContext:
    def test_returns_empty_when_no_pages(self, tmp_path):
        mem = WikiMemory(tmp_path / "empty")
        assert mem.build_context() == ""

    def test_includes_page_content(self, wiki):
        wiki.ingest("concepts", "memory", "# Memory\n\nLLM Wiki pattern.")
        ctx = wiki.build_context()
        assert "LLM Wiki pattern" in ctx
        assert "Agent Memory" in ctx

    def test_respects_max_pages(self, wiki):
        for i in range(5):
            wiki.ingest("concepts", f"page{i}", f"# Page {i}\n\nContent {i}.")
        ctx = wiki.build_context(max_pages=2)
        # Should only include 2 pages
        assert ctx.count("###") == 2


class TestAutoLink:
    def test_inserts_wikilinks(self, wiki):
        wiki.ingest("concepts", "python", "# Python\n\nA programming language.")
        wiki.ingest("concepts", "fastapi", "# FastAPI\n\nBuilt with python for web apps.")
        count = wiki.auto_link()
        assert count >= 1
        content = wiki.get_page("concepts", "fastapi")
        assert "[[python]]" in content.lower() or "[[Python]]" in content

    def test_no_self_links(self, wiki):
        wiki.ingest("concepts", "python", "# python\n\nPython is great.")
        wiki.auto_link()
        content = wiki.get_page("concepts", "python")
        assert "[[python]]" not in content.lower()

    def test_does_not_double_wrap(self, wiki):
        wiki.ingest("concepts", "python", "# Python\n\nA language.")
        wiki.ingest("concepts", "fastapi", "# FastAPI\n\nUses [[python]] already.")
        wiki.auto_link()
        content = wiki.get_page("concepts", "fastapi")
        # Should not produce [[[[python]]]]
        assert "[[[[" not in content

    def test_returns_zero_when_no_matches(self, wiki):
        wiki.ingest("concepts", "alpha", "# Alpha\n\nUnique content.")
        wiki.ingest("concepts", "beta", "# Beta\n\nDifferent content.")
        count = wiki.auto_link()
        assert count == 0

    def test_empty_wiki(self, wiki):
        count = wiki.auto_link()
        assert count == 0


class TestSummarizeOldSessions:
    def test_merges_old_sessions(self, wiki):
        # Create session pages with old modification times
        wiki.ingest("sessions", "chat-old-1", "# Chat 1\n\nOld session.")
        wiki.ingest("sessions", "chat-old-2", "# Chat 2\n\nAnother old session.")

        # Set file mtimes to 48 hours ago
        for slug in ("chat-old-1", "chat-old-2"):
            path = wiki.wiki_dir / "sessions" / f"{slug}.md"
            old_time = time.time() - 48 * 3600
            os.utime(path, (old_time, old_time))

        deleted = wiki.summarize_old_sessions(max_age_hours=24)
        assert len(deleted) == 2
        assert "chat-old-1" in deleted
        assert "chat-old-2" in deleted

        # Original session pages should be gone
        assert wiki.get_page("sessions", "chat-old-1") is None
        assert wiki.get_page("sessions", "chat-old-2") is None

        # Summary page should exist in concepts
        pages = wiki.list_pages()
        concept_slugs = [p["slug"] for p in pages if p["category"] == "concepts"]
        assert any(s.startswith("summary-") for s in concept_slugs)

    def test_does_not_touch_recent_sessions(self, wiki):
        wiki.ingest("sessions", "chat-recent", "# Recent\n\nJust happened.")
        deleted = wiki.summarize_old_sessions(max_age_hours=24)
        assert deleted == []
        # Page should still exist
        assert wiki.get_page("sessions", "chat-recent") is not None

    def test_returns_empty_when_no_sessions(self, wiki):
        deleted = wiki.summarize_old_sessions(max_age_hours=24)
        assert deleted == []
