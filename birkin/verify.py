"""Osiris (v2 #3) — the independent verification gate.

Before a step (or a whole goal) is declared done, Osiris checks the result
against its acceptance criterion with FRESH eyes — ideally a separate model
(``verify_model``). A PASS checks the Boulder box; a FAIL loops the step (up to a
cap). This is the "evidence gate" that turns best-effort completion into
verified completion. Named Osiris (judgment) — sibling of Neurosis / Morpheus.

The prompt builder + verdict parser are pure (testable); ``verify`` takes an
``ask`` callable so the runner is decoupled from any specific LLM/agent.
Pure standard library. (docs/v2.md #3)
"""

from __future__ import annotations

import re
from typing import Any, Callable

_FAIL_RE = re.compile(r"\b(FAIL|FAILED|NO\b|NOT MET|INCOMPLETE)\b", re.I)
_PASS_RE = re.compile(r"\b(PASS|PASSED|MET|DONE|YES\b|VERIFIED)\b", re.I)


def build_prompt(item: str, acceptance: str = "") -> str:
    """The verification prompt fed to a fresh verifier."""
    crit = (f"\nAcceptance criterion:\n{acceptance.strip()}"
            if acceptance and acceptance.strip() else "")
    return (
        "[Osiris] You are an INDEPENDENT verifier. With fresh eyes and zero "
        "benefit of the doubt, decide whether the work below actually meets its "
        "goal. Inspect the real artifacts (read files / run checks) — do not "
        "trust a claim of success.\n\n"
        f"Work to verify:\n{item.strip()}{crit}\n\n"
        "Answer on the FIRST line exactly 'VERDICT: PASS' or 'VERDICT: FAIL', "
        "then one short line of evidence. If you are unsure, FAIL.")


def parse_verdict(text: str) -> dict[str, Any]:
    """Parse a verifier reply into ``{passed: bool, reason: str}`` — conservative
    (anything not a clear PASS is treated as FAIL)."""
    t = (text or "").strip()
    first = t.split("\n", 1)[0]
    reason = t.split("\n", 1)[1].strip()[:300] if "\n" in t else first[:300]
    # An explicit FAIL anywhere on the verdict line wins; else require a PASS.
    if _FAIL_RE.search(first):
        return {"passed": False, "reason": reason or "verifier said FAIL"}
    if _PASS_RE.search(first):
        return {"passed": True, "reason": reason or "verifier said PASS"}
    return {"passed": False, "reason": reason or "no clear verdict — treated as FAIL"}


def verify(ask: Callable[[str], str], item: str, acceptance: str = "",
           *, label: str = "step") -> dict[str, Any]:
    """Run one verification pass. ``ask`` is ``callable(prompt) -> reply`` (a
    fresh agent/subagent, ideally on ``verify_model``). Never raises — an error
    becomes a conservative FAIL so a broken verifier can't wave work through."""
    try:
        reply = ask(build_prompt(item, acceptance))
    except Exception as exc:  # a broken verifier must not pass work
        return {"passed": False, "reason": f"verifier error: {exc}", "label": label}
    out = parse_verdict(reply)
    out["label"] = label
    return out
