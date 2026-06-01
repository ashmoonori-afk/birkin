"""Model router (v2 #1) — map a turn's task class to a model, free-tier only.

Cheap turns (typos, renames) should not burn the biggest model; hard reasoning
should not be done by the smallest. ``classify`` buckets the request and
``pick_model`` resolves a model for the current provider, **staying within the
subscription tiers** (no paid-API routing). Off by default (``model_routing``);
``model_routes`` overrides any class. Consumed by the Odyssey cycle (per step)
and available to any surface that wants per-turn selection.

Pure standard library. Borrowed from oh-my-openagent's task-category routing
(docs/v2.md #1), adapted to birkin's claude/codex tiers.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Claude-subscription tier per task class (free; no API metering).
_CLAUDE_ROUTES = {"quick": "haiku", "reason": "opus", "visual": "sonnet",
                  "deep": "opus", "default": "sonnet"}

_VISUAL_RE = re.compile(
    r"\b(ui|ux|css|html|layout|button|component|screen|frontend|image|icon|svg|"
    r"diagram|chart|color)\b", re.I)
_REASON_RE = re.compile(
    r"\b(architect\w*|design|refactor|debug|root[ -]?cause|trade[ -]?off|"
    r"algorithm|concurren\w+|optimi[sz]e|why\b|prove|reason|plan\b|strategy)\b", re.I)
_QUICK_RE = re.compile(
    r"\b(typo|rename|format|lint|bump|comment|import|whitespace|indent|"
    r"one[- ]?liner|small fix|quick)\b", re.I)


def classify(text: str) -> str:
    """Bucket a request into quick | reason | visual | default."""
    t = text or ""
    if _VISUAL_RE.search(t):
        return "visual"
    if _REASON_RE.search(t):
        return "reason"
    if _QUICK_RE.search(t) and len(t) < 240:
        return "quick"
    return "default"


def pick_model(cfg: dict[str, Any], text: str, *,
               provider: Optional[str] = None) -> Optional[str]:
    """Model to use for this turn, or ``None`` to keep the current model.

    Returns None when routing is off, or when the provider has no tier mapping
    and the user gave no explicit ``model_routes`` override — i.e. never guesses
    a model name for a provider we don't know how to tier.
    """
    cfg = cfg or {}
    if not cfg.get("model_routing", False):
        return None
    provider = provider if provider is not None else cfg.get("provider", "")
    cls = classify(text)
    routes = cfg.get("model_routes") or {}
    if isinstance(routes, dict) and routes.get(cls):
        return str(routes[cls])
    if provider == "claude-cli":
        return _CLAUDE_ROUTES.get(cls, _CLAUDE_ROUTES["default"])
    return None
