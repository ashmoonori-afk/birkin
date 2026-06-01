"""Boulder (v2 #5) — resumable checkbox-plan state for goal execution.

A goal is broken into an ordered list of small, independently-verifiable steps;
each step is checked off only after Osiris (verify.py) confirms it. The plan
lives on disk (``~/.birkin/boulder/<slug>.json``, atomic + 0o600 via ``store``)
so an interrupted run — crash, context limit — resumes from the first unchecked
step. The Odyssey skill drives this; Morpheus could reuse it for a headless run.

Pure standard library. Borrowed from oh-my-openagent's "Durable Boulder" +
.jsonl ledger idea (docs/v2.md #5).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config, neurosis, store


def boulder_dir() -> Path:
    d = config.birkin_home() / "boulder"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(slug: str) -> Path:
    return boulder_dir() / f"{slug}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_step(step: Any) -> dict[str, Any]:
    """Accept a plain title string or a ``{title, acceptance}`` dict."""
    if isinstance(step, str):
        return {"title": step, "acceptance": "", "done": False, "verdict": ""}
    return {"title": str(step.get("title", "")).strip() or "(step)",
            "acceptance": str(step.get("acceptance", "")),
            "done": bool(step.get("done", False)),
            "verdict": str(step.get("verdict", ""))}


def create(goal: str, steps: list[Any], *,
           cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Create (or RESUME, never clobber) a boulder plan for ``goal``.

    If an active plan for the same idea-slug exists it is returned unchanged, so
    re-running a goal continues instead of wiping in-progress checks.
    """
    slug = neurosis._slug(goal)
    p = _path(slug)
    existing = store._read_json(p, None)
    if isinstance(existing, dict) and existing.get("active"):
        return _descriptor(existing, resumed=True)
    # Fresh steps always start UNCHECKED — only check() (after Osiris) may flip
    # done, so a caller can't smuggle in pre-verified work (evidence gate).
    fresh = [{**_norm_step(s), "done": False, "verdict": ""} for s in (steps or [])]
    if not fresh:
        # An empty plan would be active-but-uncompletable (a zombie): next_index
        # is None and check() can't run. Fail loud rather than create one.
        raise ValueError("boulder plan needs at least one step")
    now = _now()
    state = {
        "active": True, "id": uuid.uuid4().hex, "goal": goal, "slug": slug,
        "created_at": now, "updated_at": now,
        "steps": fresh,
        "max_iters": int((cfg or {}).get("boulder_max_iters", 100)),
    }
    store._write_json(p, state)
    store.append_activity(f"boulder: created '{goal[:80]}' ({len(state['steps'])} steps)")
    return _descriptor(state, resumed=False)


def load(slug: str) -> Optional[dict[str, Any]]:
    rec = store._read_json(_path(slug), None)
    return rec if isinstance(rec, dict) else None


def next_index(state: dict[str, Any]) -> Optional[int]:
    """0-indexed position of the first unchecked step, or None when all done."""
    for i, s in enumerate(state.get("steps", [])):
        if not s.get("done"):
            return i
    return None


def remaining(state: dict[str, Any]) -> int:
    return sum(1 for s in state.get("steps", []) if not s.get("done"))


def check(slug: str, index: int, *, verdict: str = "") -> dict[str, Any]:
    """Mark step ``index`` done (with an Osiris verdict) and persist immutably.
    When the last step is checked the plan is marked inactive (goal complete)."""
    state = load(slug)
    if state is None:
        raise KeyError(f"no boulder plan: {slug}")
    steps = [dict(s) for s in state.get("steps", [])]
    if not (0 <= index < len(steps)):
        raise IndexError(f"step {index} out of range (plan has {len(steps)})")
    steps[index] = {**steps[index], "done": True, "verdict": verdict}
    done_all = all(s.get("done") for s in steps)
    new_state = {**state, "steps": steps, "active": not done_all,
                 "updated_at": _now()}
    store._write_json(_path(slug), new_state)
    store.append_activity(
        f"boulder: step {index + 1}/{len(steps)} done"
        + (" — goal complete" if done_all else ""))
    return _descriptor(new_state, resumed=False)


def active() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in boulder_dir().glob("*.json"):
        rec = store._read_json(p, None)
        if isinstance(rec, dict) and rec.get("active"):
            out.append(_descriptor(rec, resumed=False))
    out.sort(key=lambda d: str(d.get("created_at", "")))
    return out


def _descriptor(state: dict[str, Any], *, resumed: bool) -> dict[str, Any]:
    steps = state.get("steps", [])
    done = sum(1 for s in steps if s.get("done"))
    return {
        "slug": state.get("slug", ""), "goal": state.get("goal", ""),
        "total": len(steps), "done": done, "remaining": len(steps) - done,
        "active": bool(state.get("active")), "next_index": next_index(state),
        "steps": steps, "path": str(_path(state.get("slug", ""))),
        "resumed": resumed, "created_at": state.get("created_at", ""),
    }
