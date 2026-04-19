"""Tests for Memory Audit Trail."""

from __future__ import annotations

from birkin.memory.audit import MemoryAuditor
from birkin.memory.event_store import EventStore
from birkin.memory.wiki import WikiMemory


def _make_store(tmp_path) -> EventStore:
    return EventStore(db_path=tmp_path / "audit_test.db")


class TestMemoryAuditor:
    def test_log_write_and_retrieve(self, tmp_path):
        store = _make_store(tmp_path)
        auditor = MemoryAuditor(store)

        auditor.log_write("concepts", "python", "auto_classified", 0.8, "from session s1")

        history = auditor.get_page_history("concepts", "python")
        assert len(history) == 1
        assert history[0]["audit_action"] == "memory_write"
        assert history[0]["slug"] == "python"
        assert history[0]["confidence"] == 0.8

    def test_log_access_and_retrieve(self, tmp_path):
        store = _make_store(tmp_path)
        auditor = MemoryAuditor(store)

        auditor.log_access("concepts", "python", "context injection", "s2")

        history = auditor.get_page_history("concepts", "python")
        assert len(history) == 1
        assert history[0]["audit_action"] == "memory_access"

    def test_full_audit(self, tmp_path):
        store = _make_store(tmp_path)
        auditor = MemoryAuditor(store)

        auditor.log_write("concepts", "a", "auto", 0.5, "test")
        auditor.log_access("concepts", "b", "context", "s1")

        trail = auditor.get_full_audit()
        assert len(trail) == 2

    def test_explain_memory(self, tmp_path):
        store = _make_store(tmp_path)
        wiki = WikiMemory(root=tmp_path / "mem")
        wiki.init()
        wiki.ingest("concepts", "python", "# Python\n\nGreat language. See [[fastapi]].")

        auditor = MemoryAuditor(store)
        auditor.log_write("concepts", "python", "auto", 0.9, "from chat")
        auditor.log_access("concepts", "python", "context", "s1")
        auditor.log_access("concepts", "python", "context", "s2")

        info = auditor.explain_memory("concepts", "python", wiki)
        assert info["slug"] == "python"
        assert info["source"] == "auto"
        assert info["confidence"] == 0.9
        assert info["times_accessed"] == 2
        assert info["times_updated"] == 1
        assert "fastapi" in info["connections"]

    def test_explain_missing_page(self, tmp_path):
        store = _make_store(tmp_path)
        auditor = MemoryAuditor(store)
        info = auditor.explain_memory("concepts", "nonexistent")
        assert "(page not found)" in info["what"]
