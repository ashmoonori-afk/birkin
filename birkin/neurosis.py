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

import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config, store

DEFAULT_THRESHOLD = 0.05
RESOLUTION_THRESHOLDS = {"quick": 0.6, "standard": 0.5, "deep": 0.35}
# Keep word characters of ANY script, not just ASCII. birkin's house rule is
# 대화는 한국어, so ideas normally arrive in Korean — an ASCII-only rule erased
# them completely and sent every Korean idea to the timestamp fallback below,
# which made slugs neither unique (two ideas in the same second collided onto
# one interview) nor stable (the same idea a second later started a new one).
_SLUG_RE = re.compile(r"[\W_]+", re.UNICODE)


def neurosis_dir() -> Path:
    d = config.birkin_home() / "neurosis"
    d.mkdir(parents=True, exist_ok=True)
    return d


def specs_dir() -> Path:
    d = config.birkin_home() / "specs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(idea: str, *, n: int = 48) -> str:
    raw = (idea or "").strip()
    full = _SLUG_RE.sub("-", raw.lower()).strip("-")
    if len(full) > n:
        # Plain truncation would collide distinct ideas sharing a kebab prefix,
        # silently resuming the wrong interview. Append a short deterministic
        # hash of the FULL normalized string: the same idea always maps to the
        # same slug (resume stays stable) while distinct long ideas diverge.
        digest = hashlib.sha256(full.encode("utf-8")).hexdigest()[:8]
        body = full[: max(1, n - 9)].strip("-")
        full = f"{body}-{digest}"
    if full:
        return full
    if raw:
        # Nothing survived normalization (all punctuation/emoji) but there IS an
        # idea — hash it rather than stamping the clock, or the same idea would
        # never resume.
        return "idea-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return datetime.now(timezone.utc).strftime("idea-%Y%m%d-%H%M%S")


def resolve_threshold(cfg: dict[str, Any], *, resolution: Optional[str] = None,
                      override: Optional[float] = None) -> tuple[float, str]:
    """Precedence: explicit override > config ``neurosis_threshold`` > resolution
    preset (quick/standard/deep) > default 0.05. Returns (threshold, source)."""
    if override is not None:
        # An explicit override wins — but a bad value must fail loudly, not fall
        # through to config/default (that would silently ignore the user's flag).
        if not 0 < float(override) <= 1:
            raise ValueError(
                f"neurosis threshold override must be in (0, 1], got {override!r}")
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
        thr = float(existing.get("threshold", DEFAULT_THRESHOLD))
        src = str(existing.get("threshold_source", "default"))
        res = str(existing.get("resolution", "standard"))
        # A plain resume keeps the active interview's tuning; but an explicit
        # --quick/--standard/--deep or --threshold on resume RE-TUNES it instead
        # of being silently dropped. Rebuild immutably and persist.
        if threshold_override is not None or resolution is not None:
            thr, src = resolve_threshold(cfg, resolution=resolution,
                                         override=threshold_override)
            if resolution is not None:
                res = resolution
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            updated = {**existing, "threshold": thr, "threshold_source": src,
                       "resolution": res, "updated_at": now}
            if isinstance(updated.get("state"), dict):
                updated["state"] = {**updated["state"], "threshold": thr,
                                    "threshold_source": src}
            store._write_json(sp, updated)
            existing = updated
        return _descriptor(slug, existing.get("idea", idea), thr, src, res, sp,
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


def auto_trigger_note(cfg: dict[str, Any]) -> str:
    """System-prompt guidance so the agent self-runs neurosis for vague/complex
    work, instead of guessing. Empty when ``neurosis_auto`` is off."""
    if not (cfg or {}).get("neurosis_auto", True):
        return ""
    sk = skill_path()
    where = f" (read {sk})" if sk else ""
    home = config.birkin_home()
    return (
        "\n\n## Deep interview (neurosis) — when to run it automatically\n"
        "If the user's request is a COMPLEX or VAGUE work instruction or project "
        "plan that lacks a clear goal, constraints, and acceptance criteria, do NOT "
        "guess or jump straight to work. Run the **neurosis** skill" + where +
        " and interview them ONE question at a time (한국어로) until ambiguity is "
        "low, then write the spec and act only after approval. For specific, "
        "well-scoped, or simple requests, act directly — do not interview. Do NOT "
        "ask permission to interview and do NOT surface tool/skill names to the "
        "user; instead open naturally with a statement of intent, e.g. "
        "'진행 전에 모호한 부분과 핵심 결정사항을 다시 한번 확인하겠습니다.', then ask "
        "the first clarifying question. If you start an interview "
        "without the /neurosis launcher, derive your own slug from the idea and use "
        f"state {home}/neurosis/<slug>.json and spec {home}/specs/"
        "neurosis-<slug>.md (threshold: config neurosis_threshold, else 0.05).")


def start_prompt(seed: dict[str, Any]) -> str:
    """The message a surface feeds to the agent to begin/resume the interview."""
    load = ("If you have a load_skill tool, call load_skill('neurosis'); "
            "otherwise read and follow birkin's bundled neurosis skill (SKILL.md).")
    if seed.get("resume"):
        return (
            "Resume the **neurosis** deep-interview. " + load + "\n"
            f"- state_path: {seed['state_path']} (READ it; continue from the last round)\n"
            f"- spec_path: {seed['spec_path']}\n"
            f"- threshold: {seed['threshold']} ({seed['threshold_percent']}, "
            f"source: {seed['threshold_source']}) — keep this internal\n"
            "Open naturally (no tool names / no permission question), briefly "
            "summarize where we left off, then ask the next single question (한국어로).")
    return (
        "Run the **neurosis** deep-interview skill now. " + load + "\n"
        "Follow it EXACTLY for this run:\n"
        f"- idea: {seed['idea']}\n"
        f"- threshold: {seed['threshold']} ({seed['threshold_percent']}, "
        f"source: {seed['threshold_source']})\n"
        f"- resolution: {seed['resolution']}\n"
        f"- state_path: {seed['state_path']} (persist each round here)\n"
        f"- spec_path: {seed['spec_path']} (write the final English spec here)\n"
        "Begin with Phase 0 (resolve the threshold INTERNALLY; open naturally with "
        "'진행 전에 모호한 부분과 핵심 결정사항을 다시 한번 확인하겠습니다' — no permission "
        "question, no tool/skill names), then Round 0 topology. Ask ONE question "
        "(한국어로) and stop for my answer.")
