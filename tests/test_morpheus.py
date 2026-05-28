"""Tests for the Morpheus (nightly 04:00 self-improvement) routine.

We cover the pure data-gathering helpers (`_gather_sessions`,
`_gather_changed_files`) and the propose-tool wiring. The end-to-end
``run_once`` requires a live LLM, so it stays in the live harness — here
we verify the deterministic, file-system-driven slices.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from birkin import config, morpheus, store


# ---------------- _gather_sessions ----------------------------------------

def test_gather_sessions_returns_placeholder_when_empty():
    text = morpheus._gather_sessions()
    assert "no saved conversations" in text


def test_gather_sessions_includes_recent_transcript(tmp_path):
    sdir = config.sessions_dir()
    f = sdir / "s1.json"
    f.write_text(json.dumps([
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ]), encoding="utf-8")
    text = morpheus._gather_sessions()
    assert "session s1" in text
    assert "hello" in text or "hi" in text   # transcript_from_messages output


def test_gather_sessions_excludes_old_files(tmp_path):
    sdir = config.sessions_dir()
    old = sdir / "old.json"
    old.write_text(json.dumps([
        {"role": "user", "content": [{"type": "text", "text": "ancient"}]}
    ]), encoding="utf-8")
    # Backdate 48 hours so the 24h cutoff excludes it.
    ago = time.time() - 48 * 3600
    import os as _os
    _os.utime(old, (ago, ago))
    text = morpheus._gather_sessions(hours=24.0)
    assert "ancient" not in text


# ---------------- _gather_changed_files -----------------------------------

def test_gather_changed_files_lists_recent_files(tmp_path):
    (tmp_path / "fresh.md").write_text("x", encoding="utf-8")
    text = morpheus._gather_changed_files(tmp_path)
    assert "fresh.md" in text


def test_gather_changed_files_skips_excluded_dirs(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "secret").write_text("noise", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk").write_text("x", encoding="utf-8")
    (tmp_path / "real.txt").write_text("real", encoding="utf-8")
    text = morpheus._gather_changed_files(tmp_path)
    assert "real.txt" in text
    assert "secret" not in text and "junk" not in text


def test_gather_changed_files_caps_at_limit(tmp_path):
    for i in range(80):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    text = morpheus._gather_changed_files(tmp_path, limit=10)
    # exactly 10 lines, each prefixed with "- "
    assert text.count("\n- ") + (1 if text.startswith("- ") else 0) == 10


def test_gather_changed_files_returns_placeholder_when_none(tmp_path):
    """A directory with no fresh files yields the placeholder string."""
    ago = time.time() - 48 * 3600
    (tmp_path / "old.txt").write_text("x", encoding="utf-8")
    import os as _os
    _os.utime(tmp_path / "old.txt", (ago, ago))
    text = morpheus._gather_changed_files(tmp_path, hours=24.0)
    assert "no files changed" in text


# ---------------- run_once error paths ------------------------------------

def test_run_once_skips_cleanly_without_a_backend(monkeypatch):
    """No API key + no CLI backend should yield a ``morpheus skipped`` run
    record and exit 1 — never crash."""
    # config defaults to provider=anthropic and there is no key in the test
    # environment (conftest scrubs them) → ConfigError → graceful skip.
    rc = morpheus.run_once(dry_run=False)
    assert rc == 1
    runs = store.list_runs(limit=5)
    assert any("morpheus" in (r.get("kind") or "") for r in runs)
    assert any("skipped" in (r.get("summary") or "") for r in runs)


# ---------------- propose-tool ---------------------------------------------

def test_attach_propose_tool_records_dry_run_call():
    """In dry-run mode propose_action must NOT queue the proposal; it just
    returns a string and leaves the approval store untouched."""
    cfg = config.load_config()
    cfg["auto_approve"] = []

    class _FakeRegistry:
        def __init__(self):
            self.tools = {}
        def register(self, tool):
            self.tools[tool.name] = tool

    class _FakeAgent:
        registry = _FakeRegistry()

    class _FakeSession:
        agent = _FakeAgent()

    proposals: list[dict] = []
    morpheus._attach_propose_tool(_FakeSession(), cfg, proposals, dry_run=True)
    tool = _FakeSession().agent.registry.tools["propose_action"]
    result = tool.fn({"category": "cron", "title": "T",
                      "payload": {"name": "x"}}, None)
    assert "dry-run" in result.content
    assert proposals == []   # nothing queued in dry-run


def test_attach_propose_tool_queues_when_not_auto_approved():
    """Without ``cron`` in auto_approve the proposal is queued in the
    pending store, not executed."""
    cfg = config.load_config()
    cfg["auto_approve"] = []

    class _FakeRegistry:
        def __init__(self):
            self.tools = {}
        def register(self, tool):
            self.tools[tool.name] = tool

    class _FakeAgent:
        registry = _FakeRegistry()

    class _FakeSession:
        agent = _FakeAgent()

    proposals: list[dict] = []
    morpheus._attach_propose_tool(_FakeSession(), cfg, proposals, dry_run=False)
    tool = _FakeSession().agent.registry.tools["propose_action"]
    result = tool.fn({"category": "cron", "title": "morning digest",
                      "payload": {"name": "morning", "hour": 8, "minute": 0,
                                  "type": "prompt", "value": "summarize"}},
                     None)
    assert "Queued for approval" in result.content
    pending = store.list_pending()
    assert any(p["title"] == "morning digest" for p in pending)
    assert proposals and proposals[0]["category"] == "cron"


# ---------------- task template ------------------------------------------

def test_morpheus_task_template_contains_required_sections():
    """The prompt must keep the three-section structure Morpheus relies on
    (last-24h conversations + changed files + activity log) and the
    "do all that apply" instruction list."""
    rendered = morpheus._MORPHEUS_TASK.format(
        date="2026-05-28", dry="", sessions="(none)",
        files="(none)", activity="(none)")
    assert "Last 24h — conversations" in rendered
    assert "Last 24h — changed files" in rendered
    assert "Recent activity log" in rendered
    assert "propose_action" in rendered
    assert "memory_write_note" in rendered
