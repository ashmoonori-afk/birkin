"""Token-budget governor (P3 reliability).

Sums ``estTokens`` from the run ledger over a time window and decides whether
an upcoming turn would exceed the configured daily / monthly cap. Costs aren't
queried from the provider — we use birkin's own usage estimate (≈ chars/4) so
the gate is **transparent and dependency-free**. ``0`` caps mean *unlimited*.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import store


def _parse(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    # Externally-edited / legacy records may carry a naive timestamp; treat it as
    # UTC so the ``ts < cutoff`` comparison below never raises naive-vs-aware
    # TypeError (which would crash is_over() on every turn).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def usage_window(hours: float) -> int:
    """Sum of ``estTokens`` across run records newer than ``hours`` ago."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    total = 0
    for rec in store.list_runs(limit=1000):
        ts = _parse(str(rec.get("at", "")))
        if ts is None or ts < cutoff:
            continue
        total += int((rec.get("usage") or {}).get("estTokens", 0) or 0)
    return total


def status(cfg: dict[str, Any]) -> dict[str, Any]:
    """Current usage vs caps. ``0`` means no cap."""
    daily = int(cfg.get("budget_tokens_daily", 0) or 0)
    monthly = int(cfg.get("budget_tokens_monthly", 0) or 0)
    used_today = usage_window(24)
    used_month = usage_window(24 * 30)
    return {
        "used_today": used_today,
        "used_month": used_month,
        "daily_cap": daily,
        "monthly_cap": monthly,
        "over_daily": daily > 0 and used_today >= daily,
        "over_monthly": monthly > 0 and used_month >= monthly,
    }


def is_over(cfg: dict[str, Any]) -> tuple[bool, str]:
    """Return (over, human_message). False/"" when within budget."""
    # Hot path (called once per turn). With no caps configured there is nothing
    # to enforce, so skip the full ledger scan (`usage_window` reads up to 1000
    # run files) entirely — unlimited users shouldn't pay a per-turn stat tax.
    if not (int(cfg.get("budget_tokens_daily", 0) or 0)
            or int(cfg.get("budget_tokens_monthly", 0) or 0)):
        return False, ""
    st = status(cfg)
    if st["over_daily"]:
        return True, (f"[birkin] daily token budget reached: "
                      f"used {st['used_today']} / cap {st['daily_cap']}. "
                      f"Raise `budget_tokens_daily` in config or wait until tomorrow.")
    if st["over_monthly"]:
        return True, (f"[birkin] monthly token budget reached: "
                      f"used {st['used_month']} / cap {st['monthly_cap']}. "
                      f"Raise `budget_tokens_monthly` or wait until next month.")
    return False, ""
