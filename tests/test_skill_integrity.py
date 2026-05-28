"""Tests for P6: skill integrity (frontmatter lint + py_compile bundled scripts)
and risk-tiered approval inbox."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin import approvals, config, risk, store
from birkin.skills import validate as skv


# ---------------- helpers ---------------------------------------------------

def _write_skill(skills_dir: Path, name: str, frontmatter_extra: str = "",
                 body: str = "## When to Use\n\nWhen testing.") -> Path:
    """Drop a minimal-but-valid SKILL.md into ``skills_dir/<name>/``."""
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm = (
        "---\n"
        f"name: {name}\n"
        f'description: "test skill {name}"\n'
        "version: 1.0.0\n"
        "license: MIT\n"
        f"{frontmatter_extra}"
        "---\n\n"
    )
    p = skill_dir / "SKILL.md"
    p.write_text(fm + body + "\n", encoding="utf-8")
    return p


def _write_script(skills_dir: Path, skill: str, name: str, code: str) -> Path:
    d = skills_dir / skill / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(code, encoding="utf-8")
    return p


# ---------------- frontmatter lint ------------------------------------------

def test_validate_clean_skill_has_no_errors():
    cfg = config.load_config()
    _write_skill(config.user_skills_dir(), "clean")
    summary = skv.validate_all(cfg)
    rep = next(r for r in summary.reports if r.name == "clean")
    assert rep.ok
    assert not rep.warnings   # all required + recommended fields present


def test_validate_missing_description_errors():
    cfg = config.load_config()
    # write SKILL.md by hand with NO description field
    d = config.user_skills_dir() / "no-desc"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: no-desc\nversion: 1.0.0\nlicense: MIT\n---\n\n"
        "## When to Use\n\nNever.\n", encoding="utf-8")
    summary = skv.validate_all(cfg)
    rep = next(r for r in summary.reports if r.name == "no-desc")
    assert not rep.ok
    assert any("description" in e for e in rep.errors)


def test_validate_missing_recommended_fields_warns_not_errors():
    cfg = config.load_config()
    d = config.user_skills_dir() / "minimal"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: minimal\ndescription: m\n---\n\n## When to Use\n\nx\n",
        encoding="utf-8")
    summary = skv.validate_all(cfg)
    rep = next(r for r in summary.reports if r.name == "minimal")
    assert rep.ok                                  # no errors
    assert any("version" in w for w in rep.warnings)
    assert any("license" in w for w in rep.warnings)


def test_validate_missing_when_to_use_warns():
    cfg = config.load_config()
    _write_skill(config.user_skills_dir(), "no-when", body="just body, no section")
    summary = skv.validate_all(cfg)
    rep = next(r for r in summary.reports if r.name == "no-when")
    assert rep.ok
    assert any("When to Use" in w for w in rep.warnings)


# ---------------- py_compile bundled scripts --------------------------------

def test_validate_broken_bundled_script_errors():
    cfg = config.load_config()
    _write_skill(config.user_skills_dir(), "broken-script")
    _write_script(config.user_skills_dir(), "broken-script", "bad.py",
                  "def : this is not python\n")
    summary = skv.validate_all(cfg)
    rep = next(r for r in summary.reports if r.name == "broken-script")
    assert not rep.ok
    assert any("py_compile" in e for e in rep.errors)


def test_validate_clean_bundled_script_compiles():
    cfg = config.load_config()
    _write_skill(config.user_skills_dir(), "good-script")
    _write_script(config.user_skills_dir(), "good-script", "ok.py",
                  "def main():\n    return 'ok'\n")
    summary = skv.validate_all(cfg)
    rep = next(r for r in summary.reports if r.name == "good-script")
    assert rep.ok


# ---------------- summary aggregation + formatter ---------------------------

def test_summary_aggregates_errors_and_warnings():
    cfg = config.load_config()
    _write_skill(config.user_skills_dir(), "ok1")
    d = config.user_skills_dir() / "bad1"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: bad1\n---\n\n",   # no description, no When-to-Use
        encoding="utf-8")
    summary = skv.validate_all(cfg)
    assert summary.n_errors >= 1
    assert not summary.ok
    text = skv.format_summary(summary)
    assert "bad1" in text
    assert "skill(s)" in text   # summary footer present


def test_format_summary_no_skills():
    """validate_dirs with empty input → 'No skills found.'"""
    summary = skv.validate_dirs([])
    assert skv.format_summary(summary) == "No skills found."


# ---------------- risk tiers ------------------------------------------------

def test_risk_for_known_categories():
    assert risk.risk_for("memory") == "low"
    assert risk.risk_for("skill") == "low"
    assert risk.risk_for("cron") == "medium"
    assert risk.risk_for("shell") == "high"


def test_risk_for_unknown_category_defaults_medium():
    """A new / unknown category must NOT be treated as low — fail safe."""
    assert risk.risk_for("payment") == "medium"
    assert risk.risk_for("") == "medium"


def test_sort_by_risk_highest_first():
    items = [
        {"category": "memory", "title": "m"},
        {"category": "shell",  "title": "s"},
        {"category": "cron",   "title": "c"},
    ]
    sorted_items = risk.sort_by_risk(items)
    assert [i["category"] for i in sorted_items] == ["shell", "cron", "memory"]


def test_risk_label_distinct_per_tier():
    labels = {risk.label(t) for t in risk.TIERS}
    assert len(labels) == len(risk.TIERS)   # no collisions


# ---------------- review_cli integrates risk -------------------------------

def test_review_cli_orders_pending_highest_risk_first(capsys, monkeypatch):
    """`birkin review` must surface the most dangerous pending action first."""
    cfg = config.load_config()
    cfg["auto_approve"] = []   # queue everything
    # propose three actions in low→high category order
    approvals.propose(category="memory", title="low note",
                      description="d", payload={}, cfg=cfg, origin="test")
    approvals.propose(category="cron", title="mid cron",
                      description="d", payload={}, cfg=cfg, origin="test")
    approvals.propose(category="shell", title="high cmd",
                      description="d", payload={"command": "true"}, cfg=cfg,
                      origin="test")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "s")  # skip each
    approvals.review_cli()
    out = capsys.readouterr().out
    # highest-risk shell appears before the memory note
    assert out.index("high cmd") < out.index("mid cron") < out.index("low note")
    # tier labels surface (no need to match exact glyph — just the word)
    assert "[high/shell]" in out
    assert "[low/memory]" in out


def test_propose_low_risk_category_still_auto_approves_when_allowed():
    """Risk tagging must NOT change auto-approval semantics — that's still
    governed by `auto_approve`."""
    cfg = config.load_config()
    assert "memory" in cfg["auto_approve"]   # default
    # memory category has no real executor, but propose() should hit the
    # `is_auto` path and return auto=True.
    res = approvals.propose(category="memory", title="t",
                            description="d", payload={}, cfg=cfg, origin="test")
    assert res["auto"] is True
