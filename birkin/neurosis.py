"""neurosis — deep-interview launcher/runtime.

The Socratic interview itself lives in the bundled ``neurosis`` skill
(``skills/planning/neurosis/SKILL.md``), driven by the agent across chat turns.
This module is the thin runtime that mirrors gajae-code's deep-interview native
handler: it resolves the ambiguity threshold, slugs the idea, seeds/loads a
resumable interview-state file (reusing ``store`` for atomic 0o600 writes),
computes the spec path, and builds the kickoff prompt the surfaces feed to the
agent to begin/resume the interview.

Ported & adapted from gajae-code (Yeachan-Heo/gajae-code). Pure standard library.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config, store

DEFAULT_THRESHOLD = 0.05
RESOLUTION_THRESHOLDS = {"quick": 0.6, "standard": 0.5, "deep": 0.35}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def neurosis_dir() -> Path:
    d = config.birkin_home() / "neurosis"
    d.mkdir(parents=True, exist_ok=True)
    return d


def specs_dir() -> Path:
    d = config.birkin_home() / "specs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(idea: str, *, n: int = 48) -> str:
    s = _SLUG_RE.sub("-", (idea or "").strip().lower()).strip("-")[:n].strip("-")
    return s or datetime.now(timezone.utc).strftime("idea-%Y%m%d-%H%M%S")


def resolve_threshold(cfg: dict[str, Any], *, resolution: Optional[str] = None,
                      override: Optional[float] = None) -> tuple[float, str]:
    """Precedence: explicit override > config ``neurosis_threshold`` > resolution
    preset (quick/standard/deep) > default 0.05. Returns (threshold, source)."""
    if override is not None and 0 < override <= 1:
        return float(override), "flag:--threshold"
    cfgval = (cfg or {}).get("neurosis_threshold")
    if isinstance(cfgval, (int, float)) and 0 < float(cfgval) <= 1:
        return float(cfgval), "config"
    if resolution in RESOLUTION_THRESHOLDS:
        return RESOLUTION_THRESHOLDS[resolution], f"flag:--{resolution}"
    return DEFAULT_THRESHOLD, "default"


def state_path(slug: str) -> Path:
    return neurosis_dir() / f"{slug}.json"


def spec_path(slug: str) -> Path:
    return specs_dir() / f"neurosis-{slug}.md"


def skill_path() -> Optional[Path]:
    """Absolute path to the bundled neurosis SKILL.md, if present."""
    for d in config.bundled_skills_dirs():
        hits = list(d.glob("**/neurosis/SKILL.md"))
        if hits:
            return hits[0]
    return None


def seed_state(idea: str, *, cfg: Optional[dict[str, Any]] = None,
               resolution: Optional[str] = None,
               threshold_override: Optional[float] = None) -> dict[str, Any]:
    """Create a fresh interview-state file and return the run descriptor."""
    cfg = cfg or config.load_config()
    slug = _slug(idea)
    sp = state_path(slug)
    specp = spec_path(slug)
    # Don't clobber an in-progress interview for the same idea — resume it.
    existing = store._read_json(sp, None)
    if isinstance(existing, dict) and existing.get("active"):
        return _descriptor(
            slug, existing.get("idea", idea),
            float(existing.get("threshold", DEFAULT_THRESHOLD)),
            str(existing.get("threshold_source", "default")),
            str(existing.get("resolution", "standard")), sp,
            Path(existing.get("spec_path", str(specp))), resume=True)
    threshold, source = resolve_threshold(cfg, resolution=resolution,
                                          override=threshold_override)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state = {
        "active": True,
        "current_phase": "interviewing",
        "skill": "neurosis",
        "resolution": resolution or "standard",
        "threshold": threshold,
        "threshold_source": source,
        "idea": idea,
        "spec_path": str(specp),
        "created_at": now,
        "updated_at": now,
        "state": {
            "interview_id": uuid.uuid4().hex,
            "type": None,  # greenfield|brownfield — set by the agent in Phase 1
            "initial_idea": idea,
            "rounds": [],
            "current_ambiguity": 1.0,
            "threshold": threshold,
            "threshold_source": source,
            "topology": {"status": "pending", "components": [], "deferrals": []},
            "ontology_snapshots": [],
        },
    }
    store._write_json(sp, state)
    return _descriptor(slug, idea, threshold, source, resolution or "standard",
                       sp, specp, resume=False)


def active_interviews() -> list[dict[str, Any]]:
    """All active interview state records, oldest first."""
    out: list[dict[str, Any]] = []
    for p in neurosis_dir().glob("*.json"):
        rec = store._read_json(p, None)
        if isinstance(rec, dict) and rec.get("active"):
            out.append({**rec, "_path": str(p), "_slug": p.stem})
    out.sort(key=lambda r: str(r.get("created_at", "")))
    return out


def seed_or_resume(arg: str, *, cfg: Optional[dict[str, Any]] = None,
                   resolution: Optional[str] = None,
                   threshold_override: Optional[float] = None
                   ) -> Optional[dict[str, Any]]:
    """An idea -> start a new interview. No idea -> resume the most recent active
    one. Returns None when there is no idea and nothing to resume."""
    idea = (arg or "").strip()
    if idea:
        return seed_state(idea, cfg=cfg, resolution=resolution,
                          threshold_override=threshold_override)
    active = active_interviews()
    if active:
        rec = active[-1]
        return _descriptor(
            rec["_slug"], rec.get("idea", ""), float(rec.get("threshold", DEFAULT_THRESHOLD)),
            str(rec.get("threshold_source", "default")), str(rec.get("resolution", "standard")),
            Path(rec["_path"]), Path(rec.get("spec_path", str(spec_path(rec["_slug"])))),
            resume=True)
    return None


def _descriptor(slug: str, idea: str, threshold: float, source: str,
                resolution: str, sp: Path, specp: Path, *, resume: bool
                ) -> dict[str, Any]:
    return {
        "slug": slug, "idea": idea, "threshold": threshold,
        "threshold_percent": f"{threshold * 100:.0f}%", "threshold_source": source,
        "resolution": resolution, "state_path": str(sp), "spec_path": str(specp),
        "resume": resume,
    }


def start_prompt(seed: dict[str, Any]) -> str:
    """The message a surface feeds to the agent to begin/resume the interview."""
    sk = skill_path()
    load = (f"If you have a load_skill tool, call load_skill('neurosis'); "
            f"otherwise read the skill file at {sk}." if sk
            else "Read and follow birkin's neurosis skill.")
    if seed.get("resume"):
        return (
            "Resume the **neurosis** deep-interview. " + load + "\n"
            f"- state_path: {seed['state_path']} (READ it; continue from the last round)\n"
            f"- spec_path: {seed['spec_path']}\n"
            f"- threshold: {seed['threshold']} ({seed['threshold_percent']}, "
            f"source: {seed['threshold_source']})\n"
            "Re-emit the Phase 0 threshold line, summarize where we left off, then "
            "ask the next single question (한국어로).")
    return (
        "Run the **neurosis** deep-interview skill now. " + load + "\n"
        "Follow it EXACTLY for this run:\n"
        f"- idea: {seed['idea']}\n"
        f"- threshold: {seed['threshold']} ({seed['threshold_percent']}, "
        f"source: {seed['threshold_source']})\n"
        f"- resolution: {seed['resolution']}\n"
        f"- state_path: {seed['state_path']} (persist each round here)\n"
        f"- spec_path: {seed['spec_path']} (write the final English spec here)\n"
        "Begin with Phase 0 (announce the threshold), then Round 0 topology. "
        "Ask ONE question (한국어로) and stop for my answer.")
