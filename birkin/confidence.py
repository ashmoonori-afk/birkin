"""Confidence-based verification tiering (thinking frameworks, item 2).

A turn leaves observable debris behind it: tool errors, schema retries,
mid-turn steers, unsupported claims, budget overruns. None of those alone
proves the answer is wrong, but together they say how much the turn's output
should be trusted *before* it is checked. This module turns that debris into
one score in [0, 1] and maps the score to a verification tier, so cheap turns
stay cheap and shaky turns get checked:

- ``fast``     — nothing went wrong; optional re-checks may be skipped.
- ``standard`` — the default; current behavior, unchanged.
- ``strict``   — enough went wrong that a verifier must pass before the work
  is treated as done.

The score is a plain monotone penalty sum (see :func:`score`) — no model
call, no state, no I/O. Consumers collect :class:`Signals` however they can
(a session counts its own events; a moirai run counts verifier outcomes) and
the module never knows the difference, which is what lets the session-side
wiring land later without touching this file.

Thresholds are config (``confidence_strict_below`` default 0.4,
``confidence_fast_above`` default 0.8) and every reader must fail open:
a malformed threshold yields the default tiering, never an exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Tier = Literal["fast", "standard", "strict"]

TIERS = ("fast", "standard", "strict")

DEFAULT_STRICT_BELOW = 0.4
DEFAULT_FAST_ABOVE = 0.8

# Penalty weights, documented so a score can be explained without reading
# code. They are deliberately uneven: a tool error is normal loop noise,
# while an unsupported claim or a blown turn budget is a much stronger sign
# the turn drifted. The sum is clamped into [0, 1], so a bad enough turn
# saturates at 0 instead of going negative.
W_TOOL_ERROR = 0.10
W_SCHEMA_RETRY = 0.15
W_STEER = 0.05
W_UNSUPPORTED_CLAIM = 0.20
W_OVER_BUDGET = 0.25


@dataclass(frozen=True)
class Signals:
    """What one turn (or one run) left behind. All counts default to zero,
    so a caller that only knows about one kind of signal can set just that
    field and still get a sane score."""

    tool_errors: int = 0
    schema_retries: int = 0
    steer_count: int = 0
    unsupported_claims: int = 0
    turns_over_budget: bool = False


def score(signals: Signals) -> float:
    """Map signals to a confidence score in [0, 1]; 1.0 is a clean turn.

    Monotone: raising any count (or flipping the budget flag) never raises
    the score. Negative counts are treated as zero rather than rejected —
    the caller's bookkeeping bug must not crash the turn it was measuring.
    """
    penalty = (
        W_TOOL_ERROR * max(0, int(signals.tool_errors))
        + W_SCHEMA_RETRY * max(0, int(signals.schema_retries))
        + W_STEER * max(0, int(signals.steer_count))
        + W_UNSUPPORTED_CLAIM * max(0, int(signals.unsupported_claims))
        + (W_OVER_BUDGET if signals.turns_over_budget else 0.0)
    )
    return max(0.0, min(1.0, 1.0 - penalty))


def _threshold(cfg: dict[str, Any] | None, key: str, default: float) -> float:
    try:
        value = float((cfg or {}).get(key, default))
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def tier(value: float, cfg: dict[str, Any] | None = None) -> Tier:
    """Map a confidence score to a verification tier.

    ``confidence_strict_below`` (default 0.4): strictly below this is
    ``strict``. ``confidence_fast_above`` (default 0.8): at or above this is
    ``fast``. Everything between is ``standard``. If an override inverts the
    band (strict threshold above the fast one) the defaults win — a config
    typo must not silently flip every turn into one tier.
    """
    strict_below = _threshold(cfg, "confidence_strict_below",
                              DEFAULT_STRICT_BELOW)
    fast_above = _threshold(cfg, "confidence_fast_above", DEFAULT_FAST_ABOVE)
    if strict_below >= fast_above:
        strict_below, fast_above = DEFAULT_STRICT_BELOW, DEFAULT_FAST_ABOVE
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "standard"
    if value < strict_below:
        return "strict"
    if value >= fast_above:
        return "fast"
    return "standard"


def tier_for(signals: Signals, cfg: dict[str, Any] | None = None) -> Tier:
    """Convenience composition: ``tier(score(signals), cfg)``."""
    return tier(score(signals), cfg)
