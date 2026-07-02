"""Skill curator: usage tracking + stale/archive lifecycle (hermes rules)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from birkin import config, curator
from birkin.skills import build_manager


def _make_user_skill(name: str, *, age_days: float = 0.0) -> Path:
    d = config.user_skills_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(f"---\nname: {name}\ndescription: test skill\n---\n\nbody\n",
                 encoding="utf-8")
    if age_days:
        ago = time.time() - age_days * 86400
        os.utime(p, (ago, ago))
    return d


def test_record_use_roundtrip_and_count():
    curator.record_use("alpha")
    curator.record_use("alpha")
    usage = curator.load_usage()
    assert usage["alpha"]["count"] == 2
    assert usage["alpha"]["last_used"]


def test_fresh_skill_is_not_stale():
    _make_user_skill("newborn")
    report = curator.curate(build_manager(config.load_config()))
    assert all(s["name"] != "newborn" for s in report["stale"])
    assert "newborn" not in report["archived"]


def test_idle_user_skill_over_90d_is_archived():
    _make_user_skill("dusty", age_days=120)
    report = curator.curate(build_manager(config.load_config()))
    assert "dusty" in report["archived"]
    archive = config.user_skills_dir() / curator.ARCHIVE_DIR / "dusty"
    assert (archive / "SKILL.md").is_file()
    assert not (config.user_skills_dir() / "dusty").exists()


def test_archived_skill_leaves_the_catalog():
    _make_user_skill("ghosted", age_days=120)
    curator.curate(build_manager(config.load_config()))
    # .archive is a hidden tree — discover() must not resurrect it.
    assert build_manager(config.load_config()).get("ghosted") is None


def test_dry_run_reports_candidate_but_moves_nothing():
    _make_user_skill("pending", age_days=120)
    report = curator.curate(build_manager(config.load_config()), apply=False)
    assert report["archived"] == []
    assert any(s["name"] == "pending" and s["idle_days"] >= 90
               for s in report["stale"])
    assert (config.user_skills_dir() / "pending" / "SKILL.md").is_file()
    assert "archive candidate" in curator.render_report(report)


def test_idle_30_to_90d_is_stale_not_archived():
    _make_user_skill("napping", age_days=45)
    report = curator.curate(build_manager(config.load_config()))
    assert any(s["name"] == "napping" for s in report["stale"])
    assert "napping" not in report["archived"]


def test_recent_usage_overrides_old_mtime():
    _make_user_skill("evergreen", age_days=120)
    curator.record_use("evergreen")
    report = curator.curate(build_manager(config.load_config()))
    assert all(s["name"] != "evergreen" for s in report["stale"])
    assert "evergreen" not in report["archived"]


def test_bundled_skills_are_reported_but_never_archived():
    mgr = build_manager(config.load_config())
    bundled = [s for s in mgr.skills.values() if s.source == "bundled"]
    if not bundled:   # source checkout always has them; be safe anyway
        return
    old = datetime.now(timezone.utc) - timedelta(days=400)
    usage = {s.name: {"count": 1, "last_used": old.isoformat()}
             for s in mgr.skills.values()}
    import json
    (config.user_skills_dir() / curator.USAGE_FILE).write_text(
        json.dumps(usage), encoding="utf-8")
    report = curator.curate(mgr)
    assert report["archived"] == []          # nothing bundled ever moves
    assert any(s["source"] == "bundled" for s in report["stale"])


def test_load_skill_tool_records_usage():
    mgr = build_manager(config.load_config())
    if not mgr.skills:
        return
    name = sorted(mgr.skills)[0]
    tool = next(t for t in mgr.tools() if t.name == "load_skill")
    res = tool.fn({"name": name}, None)
    assert not res.is_error
    assert curator.load_usage()[name]["count"] == 1
