"""Ebbinghaus note decay and zone-priority dynamics."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Final

from .index_types import NoteDynamics
from .json_types import JsonValue

STRENGTH_STEP: Final = 0.25
STRENGTH_CAP: Final = 5.0
STABILITY_INIT: Final = 7.0
STABILITY_GROWTH: Final = 1.5
STABILITY_CAP: Final = 365.0
EFF_FLOOR: Final = 0.05
SPACING_HOURS: Final = 1.0
ZONE_EMA_DECAY: Final = 0.9


def parse_datetime(raw: JsonValue) -> datetime | None:
    """Parse an ISO datetime, interpreting a naive value as UTC."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def default_dynamics(created: str | None = None) -> NoteDynamics:
    """Return fresh note dynamics, optionally anchored to its creation time."""
    created_at = parse_datetime(created) or datetime.now(timezone.utc)
    return {
        "strength": 1.0,
        "stability": STABILITY_INIT,
        "access_count": 0,
        "last_access": created_at.isoformat(),
    }


def effective_strength(dyn: NoteDynamics, now: datetime) -> float:
    """Return floored Ebbinghaus retention for one note."""
    strength = float(dyn.get("strength", 1.0))
    last_access = parse_datetime(dyn.get("last_access"))
    if last_access is None:
        return max(EFF_FLOOR, min(strength, STRENGTH_CAP))
    days = max(0.0, (now - last_access).total_seconds() / 86400.0)
    stability = max(1e-6, float(dyn.get("stability", STABILITY_INIT)))
    return max(EFF_FLOOR, strength * math.exp(-days / stability))


def potentiate(dyn: NoteDynamics, now: datetime) -> NoteDynamics:
    """Return new dynamics reinforced by one note access."""
    last_access = parse_datetime(dyn.get("last_access"))
    hours = (
        (now - last_access).total_seconds() / 3600.0
        if last_access
        else SPACING_HOURS
    )
    stability = float(dyn.get("stability", STABILITY_INIT))
    if hours >= SPACING_HOURS:
        stability = min(STABILITY_CAP, stability * STABILITY_GROWTH)
    return {
        "strength": min(
            STRENGTH_CAP,
            float(dyn.get("strength", 1.0)) + STRENGTH_STEP,
        ),
        "stability": stability,
        "access_count": int(dyn.get("access_count", 0)) + 1,
        "last_access": now.isoformat(),
    }


def decayed_ema(ema: float, last_hit: str | None, today: date) -> float:
    """Decay a zone EMA lazily by the days since its last access."""
    if not last_hit:
        return float(ema)
    try:
        days = max(0, (today - date.fromisoformat(str(last_hit))).days)
    except ValueError:
        return float(ema)
    return float(ema) * (ZONE_EMA_DECAY ** days)
