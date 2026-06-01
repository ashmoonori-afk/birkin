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
_CLAUDE_TIER = set(_CLAUDE_ROUTES.values())          # {haiku, opus, sonnet}
# Only the subscription CLI backends may be routed — never a paid API provider.
_FREE_CLI = ("claude-cli", "codex-cli", "local-cli")

_VISUAL_RE = re.compile(
    r"\b(ui|ux|css|html|layout|button|component|screen|frontend|image|icon|svg|"
    r"diagram|chart|color)\b", re.I)
_REASON_RE = re.compile(
    r"\b(architect\w*|design|refactor|debug|root[ -]?cause|trade[ -]?off|"
    r"algorithm|concurren\w+|optimi[sz]e|why\b|prove|reason|plan\b|strategy)\b", re.I)
# NB: 'import'/'comment' deliberately omitted — they are overloaded (a trivial
# edit AND a feature noun, e.g. "add a comment system"), so keying on them
# mis-routed real features to the weakest tier.
_QUICK_RE = re.compile(
    r"\b(typo|rename|format|lint|bump|whitespace|indent|"
    r"one[- ]?liner|small fix|quick fix)\b", re.I)


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
    # Free/OAuth guarantee: NEVER route a paid API provider (anthropic/openai) —
    # the user already chose that paid model; routing among paid models is out of
    # scope and would meter tokens. Only the subscription CLIs are routed.
    if provider not in _FREE_CLI:
        return None
    cls = classify(text)
    routes = cfg.get("model_routes") or {}
    override = (str(routes[cls]) if isinstance(routes, dict) and routes.get(cls)
                else None)
    if provider == "claude-cli":
        # Keep claude overrides within the subscription tier (haiku/opus/sonnet
        # or a claude-… full id); ignore anything else (could be a paid model).
        if override is not None and (override in _CLAUDE_TIER
                                     or override.startswith("claude-")):
            return override
        return _CLAUDE_ROUTES.get(cls, _CLAUDE_ROUTES["default"])
    # codex-cli / local-cli: the subscription CLI validates its own -m model.
    return override
