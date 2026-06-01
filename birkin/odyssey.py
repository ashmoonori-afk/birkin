"""Odyssey (v2) — thin runtime for the goal-completion cycle skill.

Like ``neurosis.py``, this is the launcher/glue: given a GOAL it derives a slug,
points at the resumable Boulder plan, and builds the kickoff prompt that drives
the bundled ``odyssey`` skill (which composes neurosis → Hyperplan critique →
Boulder → agent[Model Router + Hashline] → Osiris verify). The cycle itself runs
as skill-protocol across turns; the primitives it leans on live in their own
modules (boulder.py, verify.py, critique.py, router.py).

Pure standard library. (docs/v2.md §3)
"""

from __future__ import annotations

from typing import Any, Optional

from . import boulder, config, intent, neurosis


def seed(goal: str, *, cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Describe an Odyssey run for ``goal`` (does NOT pre-create the plan — the
    agent writes real steps into the Boulder file during Phase 2; an active plan
    for the same slug is resumed)."""
    cfg = cfg or config.load_config()
    slug = neurosis._slug(goal)
    existing = boulder.load(slug)
    return {
        "slug": slug, "goal": goal,
        "boulder_path": str(boulder._path(slug)),
        "resume": bool(existing and existing.get("active")),
        "mode": intent.classify(goal),
        "max_iters": int((cfg or {}).get("boulder_max_iters", 100)),
        "critics": int((cfg or {}).get("critique_agents", 3)),
    }


def start_prompt(s: dict[str, Any]) -> str:
    """The goal kickoff prompt a surface feeds the agent to run the cycle."""
    head = ("Resume the **[Odyssey]** goal-completion cycle"
            if s.get("resume") else "Run the **[Odyssey]** goal-completion cycle")
    return (
        f"{head} for this GOAL:\n  goal: {s['goal']}\n"
        "Load the skill: if you have load_skill, call load_skill('odyssey'); "
        "otherwise read and follow birkin's bundled odyssey skill (SKILL.md).\n"
        "Follow it EXACTLY:\n"
        "1. If the goal is vague, run neurosis first to a spec.\n"
        f"2. Write a CHECKBOX plan (Boulder) at {s['boulder_path']} "
        "(ordered steps, each with a one-line acceptance criterion).\n"
        f"3. Have {s['critics']} adversarial critics (Hyperplan) attack the plan; "
        "revise once.\n"
        "4. Execute ONE unchecked step at a time. Pick the model by task class "
        "(quick->haiku, reasoning/architecture->opus). Edit files with "
        "hash-checked writes (read annotate=true, then edit_file) only.\n"
        "5. After each step, [Osiris] verifies it against its acceptance "
        "criterion — pass -> check the box; fail -> retry the step "
        f"(cap {s['max_iters']} total iterations).\n"
        "6. Stop when every box is checked AND [Osiris] confirms the goal. "
        "Consequential actions (shell/cron) go to the approval queue, never auto. "
        "Report progress as remaining steps (예상 남은 단계: ~N), not internals. "
        "Resume from the Boulder file if interrupted.")
