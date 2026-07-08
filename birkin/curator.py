"""Skill curator — usage tracking + stale/archive lifecycle.

Ported from hermes-agent's ``agent/curator.py`` rules: a skill unused for
30 days is *stale* (reported, nothing moves), unused for 90 days it is
*archived* — moved to ``~/.birkin/skills/.archive/<dir>/``, never deleted.
Only **user** skills are archived (bundled/extra skills are read-only
catalog; they are merely reported as stale). All transitions are LLM-free;
Morpheus receives the report and may act on it (improve/refresh a stale
skill) during the nightly pass.

Usage is recorded by the ``load_skill`` tool into
``~/.birkin/skills/.usage.json`` (``{name: {count, last_used}}``). A skill
that has never been loaded falls back to its ``SKILL.md`` mtime, so a
freshly authored skill is not instantly stale.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .mnemosyne import _parse_dt, atomic_write

USAGE_FILE = ".usage.json"
ARCHIVE_DIR = ".archive"
STALE_DAYS = 30      # hermes curator: unused -> stale
ARCHIVE_DAYS = 90    # hermes curator: stale -> archive (never delete)


def _usage_path() -> Path:
    return config.user_skills_dir() / USAGE_FILE


def load_usage() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(_usage_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def record_use(name: str) -> None:
    """Bump a skill's usage (best-effort — never fails the calling tool)."""
    if not name:
        return
    try:
        usage = load_usage()
        cur = usage.get(name) or {}
        usage[name] = {"count": int(cur.get("count", 0)) + 1,
                       "last_used": datetime.now(timezone.utc).isoformat(
                           timespec="seconds")}
        atomic_write(_usage_path(), json.dumps(usage, indent=1))
    except (OSError, TypeError, ValueError):
        pass   # incl. a hand-corrupted count — tracking must never fail a tool


def _last_activity(skill: Any, usage: dict[str, dict[str, Any]]) -> datetime:
    """Last use if recorded, else the SKILL.md mtime (authoring counts)."""
    rec = usage.get(skill.name) or {}
    dt = _parse_dt(rec.get("last_used"))
    if dt is not None:
        return dt
    try:
        return datetime.fromtimestamp(skill.path.stat().st_mtime,
                                      tz=timezone.utc)
    except OSError:
        return datetime.now(timezone.utc)   # unreadable -> treat as fresh


def _archive_skill_dir(skill_dir: Path) -> Path:
    """Move a user skill directory into ``.archive/`` (collision-safe)."""
    root = config.user_skills_dir() / ARCHIVE_DIR
    root.mkdir(parents=True, exist_ok=True)
    target = root / skill_dir.name
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        target = root / f"{skill_dir.name}-{stamp}"
    skill_dir.replace(target)
    return target


def curate(manager: Any, *, now: datetime | None = None,
           apply: bool = True) -> dict[str, Any]:
    """One lifecycle pass over the catalog.

    Returns ``{"checked", "stale": [{name, source, idle_days}], "archived"}``.
    With ``apply=False`` nothing moves; >ARCHIVE_DAYS user skills still show
    up in ``stale`` (marked as archive candidates by :func:`render_report`).
    """
    now = now or datetime.now(timezone.utc)
    usage = load_usage()
    user_root = config.user_skills_dir().resolve()
    stale: list[dict[str, Any]] = []
    archived: list[str] = []
    for skill in list(manager.skills.values()):
        idle = (now - _last_activity(skill, usage)).total_seconds() / 86400.0
        if idle < STALE_DAYS:
            continue
        skill_dir = skill.path.parent
        is_user = skill.source == "user"
        try:
            is_user = is_user and skill_dir.resolve().is_relative_to(user_root)
        except (OSError, ValueError):
            is_user = False
        if idle >= ARCHIVE_DAYS and is_user and apply:
            try:
                _archive_skill_dir(skill_dir)
                archived.append(skill.name)
                continue
            except OSError:
                pass   # busy/locked dir -> fall through, report as stale
        stale.append({"name": skill.name, "source": skill.source,
                      "idle_days": round(idle)})
    return {"checked": len(manager.skills), "stale": stale,
            "archived": archived}


def _safe_name(name: str) -> str:
    """Skill names from hand-edited/extra SKILL.md files are untrusted; make
    sure one can't smuggle the prompt's UNTRUSTED-DATA fence markers."""
    return str(name).replace("<<<", "‹‹‹").replace(">>>", "›››")


def render_report(report: dict[str, Any]) -> str:
    """Compact text block for the Morpheus prompt / ``birkin curate``."""
    lines = [f"checked {report.get('checked', 0)} skill(s)"]
    for s in report.get("stale", []):
        marker = (" — archive candidate"
                  if s.get("idle_days", 0) >= ARCHIVE_DAYS else "")
        lines.append(f"- stale: {_safe_name(s['name'])} ({s['source']}, "
                     f"idle {s['idle_days']}d){marker}")
    for name in report.get("archived", []):
        lines.append(f"- archived: {_safe_name(name)} -> skills/{ARCHIVE_DIR}/")
    if len(lines) == 1:
        lines.append("(no stale skills)")
    return "\n".join(lines)
