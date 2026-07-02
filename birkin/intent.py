"""IntentGate (v2 #4) — classify a turn's intent from explicit keywords.

A cheap, deterministic front gate: an explicit keyword routes a turn to a mode
so the heavy on-demand cycle (Odyssey) runs ONLY when asked, and clarify/search
modes are reachable by name. This complements ``neurosis_auto`` (which is the
model's judgment); IntentGate is the user's explicit override.

Modes: ``ultrawork`` (run the Odyssey goal cycle), ``plan`` (run neurosis to a
spec), ``search`` / ``analyze`` (read-only research framing), or ``normal``
(an ordinary turn — the default). Pure standard library.
"""

from __future__ import annotations

import re

# Word-boundary keyword triggers. ``ulw``/``ultrawork`` -> the Odyssey cycle.
# Korean stems are matched WITHOUT ``\b``: Hangul syllables are word characters,
# so ``\b검색해\b`` never matches the common form "검색해줘" (the trailing "줘"
# is also a word char, so there is no boundary). Stems like ``검색(해|하)`` catch
# 검색해/검색해줘/검색하고 etc.
_PATTERNS = [
    ("ultrawork", re.compile(r"\b(ultrawork|ulw)\b", re.I)),
    ("plan",      re.compile(r"\b(/?neurosis|deep[- ]?interview|plan this|"
                             r"clarify first)\b|딥\s*인터뷰|심층\s*인터뷰", re.I)),
    ("search",    re.compile(r"\b(search the web|web search|look up|find online)\b"
                             r"|검색(해|하)|웹\s*검색", re.I)),
    ("analyze",   re.compile(r"\b(analy[sz]e|audit|review this)\b"
                             r"|분석(해|하)", re.I)),
]

MODES = ("ultrawork", "plan", "search", "analyze", "normal")


def classify(text: str) -> str:
    """Return the intent mode for ``text`` (``normal`` when no keyword matches).

    First match wins, in priority order (ultrawork > plan > search > analyze).
    """
    t = text or ""
    for mode, pat in _PATTERNS:
        if pat.search(t):
            return mode
    return "normal"


def is_goal_cycle(text: str) -> bool:
    """True when the turn explicitly asks for the Odyssey goal-completion cycle."""
    return classify(text) == "ultrawork"
