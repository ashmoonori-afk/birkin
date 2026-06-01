"""Hyperplan (v2 #6) — N adversarial critics attack a plan before execution.

Cheap insurance against confidently building the wrong thing: before the Odyssey
cycle executes a Boulder plan, spawn a few HOSTILE reviewers, each with a
different lens, to find what is missing / mis-ordered / untestable / risky. Their
findings revise the plan once.

Pure builders + a thin runner (``ask`` callable, so it is decoupled and
testable). Borrowed from oh-my-openagent's ``hyperplan`` (docs/v2.md #6).
"""

from __future__ import annotations

from typing import Any, Callable

# Distinct lenses so N critics aren't redundant. Cycled to the requested count.
_LENSES = [
    ("completeness", "What steps are MISSING? What must happen that the plan omits?"),
    ("ordering", "Is any step out of order or blocked by a later one?"),
    ("testability", "Is each step's acceptance criterion concrete and verifiable?"),
    ("risk", "What is risky, destructive, or irreversible? What needs approval?"),
    ("simplicity", "What is over-built? What is the simplest plan that still works?"),
]


def lenses_for(n: int) -> list[tuple[str, str]]:
    n = max(1, int(n))
    return [_LENSES[i % len(_LENSES)] for i in range(n)]


def build_prompt(plan_text: str, lens_name: str, lens_q: str) -> str:
    """A single hostile-critic prompt for one lens."""
    return (
        f"[Hyperplan:{lens_name}] You are a HOSTILE plan reviewer. Attack the plan "
        f"below through the '{lens_name}' lens only. {lens_q}\n\n"
        f"Plan:\n{plan_text.strip()}\n\n"
        "List concrete problems as short bullets (•). If the plan is sound on this "
        "lens, reply exactly 'OK'. Be specific; do not rewrite the plan.")


def critique(ask: Callable[[str], str], plan_text: str, n: int = 3
             ) -> dict[str, Any]:
    """Run ``n`` adversarial critics (sequentially via ``ask``) and aggregate.

    ``ask`` is ``callable(prompt) -> reply``. Returns
    ``{issues: [{lens, text}], revise: bool}`` — ``revise`` is True if any critic
    raised a non-OK finding. Critic errors are skipped (never block the cycle).
    """
    issues: list[dict[str, str]] = []
    for name, q in lenses_for(n):
        try:
            reply = (ask(build_prompt(plan_text, name, q)) or "").strip()
        except Exception:
            continue
        if reply and reply.strip().upper() != "OK":
            issues.append({"lens": name, "text": reply[:800]})
    return {"issues": issues, "revise": bool(issues)}
