"""Tests for verified learning (P4): Skill-PR routing through the approval
gate, and memory TTL expiry."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from birkin import approvals, config, store
from birkin.memory import VaultMemory
from birkin.skills import build_manager


def _create_skill_tool(mgr):
    return next(t for t in mgr.tools() if t.name == "create_skill")


def _improve_skill_tool(mgr):
    return next(t for t in mgr.tools() if t.name == "improve_skill")


def _ctx(cfg):
    """ToolContext with the given cfg; the skill tools only read ctx.cfg."""
    from birkin.tools import ToolContext
    return ToolContext(cfg=cfg, client=None, cwd=Path("."),
                       skills=None, memory=None)


# ---------------- Skill-PR (auto-approved path) ----------------

def test_create_skill_auto_applies_when_skills_in_auto_approve():
    cfg = config.load_config()
    assert "skill" in cfg["auto_approve"]   # default
    mgr = build_manager(cfg)
    tool = _create_skill_tool(mgr)
    res = tool.fn({"name": "auto-pr", "description": "d", "body": "body"}, _ctx(cfg))
    assert not res.is_error
    assert "auto-approved" in res.content
    # the file was written, no pending queue used
    assert (config.user_skills_dir() / "auto-pr" / "SKILL.md").is_file()
    assert store.list_pending() == []


# ---------------- Skill-PR (queued path) ----------------

def test_create_skill_queues_when_skills_NOT_auto_approved():
    cfg = config.load_config()
    cfg["auto_approve"] = ["memory"]   # drop "skills"
    mgr = build_manager(cfg)
    tool = _create_skill_tool(mgr)
    res = tool.fn({"name": "queued-pr", "description": "d", "body": "body"}, _ctx(cfg))
    assert not res.is_error
    assert "awaiting approval" in res.content
    assert not (config.user_skills_dir() / "queued-pr" / "SKILL.md").is_file()
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["category"] == "skill"
    # approving applies the skill
    res = approvals.approve(pending[0]["id"], approved_by="human:test", approved_via="test")
    assert res["ok"] is True
    assert (config.user_skills_dir() / "queued-pr" / "SKILL.md").is_file()


# ---------------- improve_skill PR path ----------------

def test_improve_skill_appends_learned_note():
    cfg = config.load_config()
    mgr = build_manager(cfg)
    tool = _improve_skill_tool(mgr)
    # target an existing bundled skill — improve forks it into the user dir
    res = tool.fn({"name": "web-research",
                   "addition": "Always cite the URL."}, _ctx(cfg))
    assert not res.is_error
    forked = config.user_skills_dir() / "web-research" / "SKILL.md"
    assert forked.is_file()
    assert "Always cite the URL." in forked.read_text(encoding="utf-8")


def test_improve_skill_disabled_when_self_improve_off():
    cfg = config.load_config()
    cfg["self_improve"] = False
    mgr = build_manager(cfg)
    tool = _improve_skill_tool(mgr)
    res = tool.fn({"name": "web-research", "addition": "x"}, _ctx(cfg))
    assert res.is_error and "disabled" in res.content.lower()


# ---------------- Memory TTL ----------------

def _write_ttl_note(vault: VaultMemory, title: str, body: str, expires_at: str):
    """Helper: write a note then poke the expires_at directly into frontmatter."""
    p = vault.write_note(title, body, note_type="fact")
    text = p.read_text(encoding="utf-8")
    text = text.replace("---\n\n", f"expires_at: {expires_at}\n---\n\n", 1)
    p.write_text(text, encoding="utf-8")


def test_memory_ttl_excludes_expired_from_list():
    m = VaultMemory(config.load_config())
    m.write_note("Fresh", "still relevant", note_type="fact")
    _write_ttl_note(m, "Stale", "no longer", "1900-01-01")
    titles = {n["title"] for n in m.list_notes()}
    assert "Fresh" in titles and "Stale" not in titles


def test_memory_ttl_excludes_expired_from_search():
    m = VaultMemory(config.load_config())
    m.write_note("Fresh", "uniquetokenABC payload", note_type="fact")
    _write_ttl_note(m, "Stale", "uniquetokenABC payload", "1900-01-01")
    hits = {h["title"] for h in m.search("uniquetokenABC")}
    assert any("fresh" in t for t in hits) and not any("stale" in t for t in hits)


def test_memory_ttl_renders_only_live_notes():
    m = VaultMemory(config.load_config())
    m.write_note("Live one", "ok", note_type="fact")
    _write_ttl_note(m, "Old one", "ok", "1900-01-01")
    digest = m.render()
    assert "[[Live one]]" in digest
    assert "[[Old one]]" not in digest


def test_memory_ttl_get_note_still_returns_expired():
    """`get_note` is the explicit-by-name access path; it must work even for
    expired notes (debug/inspection)."""
    m = VaultMemory(config.load_config())
    _write_ttl_note(m, "Old one", "still readable", "1900-01-01")
    assert "still readable" in (m.get_note("Old one") or "")


def test_write_note_with_ttl_days_persists_expires_at():
    m = VaultMemory(config.load_config())
    p = m.write_note("Ephemeral", "body", note_type="fact", ttl_days=14)
    text = p.read_text(encoding="utf-8")
    assert "expires_at:" in text
    target = (date.today() + timedelta(days=14)).isoformat()
    assert target in text
