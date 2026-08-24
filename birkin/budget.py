"""Token-budget governor (P3 reliability).

Sums ``estTokens`` from the run ledger over a time window and decides whether
an upcoming turn would exceed the configured daily / monthly cap. Costs aren't
queried from the provider — we use birkin's own usage estimate (≈ chars/4) so
the gate is **transparent and dependency-free**. ``0`` caps mean *unlimited*.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from . import store


class TreeBudgetExceeded(RuntimeError):
    """A child could not reserve shared tree resources before execution."""


@dataclass
class TreeBudgetLease:
    budget: "TreeBudget"
    tokens: int
    usd: float
    released: bool = False

    def settle(self, *, tokens: int | None = None,
               usd: float | None = None) -> None:
        if self.released:
            return
        with self.budget._lock:
            actual_tokens = self.tokens if tokens is None else max(0, tokens)
            actual_usd = self.usd if usd is None else max(0.0, usd)
            self.budget.reserved_tokens += actual_tokens - self.tokens
            self.budget.reserved_usd += actual_usd - self.usd
            self.budget.active -= 1
        self.released = True

    def release(self) -> None:
        self.settle()


class TreeBudget:
    """One session-owned admission ledger shared by every descendant."""

    def __init__(self, cfg: dict[str, Any]):
        self.max_tokens = int(cfg.get("subagent_tree_max_tokens", 0) or 0)
        self.max_usd = float(cfg.get("subagent_tree_max_usd", 0.0) or 0.0)
        self.max_concurrent = int(
            cfg.get("subagent_tree_max_concurrent", 0) or 0
        )
        self.max_nodes = int(cfg.get("subagent_tree_max_nodes", 0) or 0)
        seconds = float(
            cfg.get("subagent_tree_deadline_seconds", 0.0) or 0.0
        )
        self.deadline = time.monotonic() + seconds if seconds > 0 else None
        self.reserved_tokens = 0
        self.reserved_usd = 0.0
        self.active = 0
        self.nodes = 0
        self._lock = threading.Lock()

    def reserve(self, *, tokens: int = 0, usd: float = 0.0) -> TreeBudgetLease:
        tokens = max(0, int(tokens))
        usd = max(0.0, float(usd))
        with self._lock:
            if self.max_tokens and tokens == 0:
                raise TreeBudgetExceeded(
                    "subagent tree token reservation required"
                )
            if self.max_usd and usd == 0.0:
                raise TreeBudgetExceeded(
                    "subagent tree USD reservation required"
                )
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise TreeBudgetExceeded("subagent tree deadline exceeded")
            if self.max_concurrent and self.active >= self.max_concurrent:
                raise TreeBudgetExceeded("subagent tree concurrent child limit")
            if self.max_nodes and self.nodes >= self.max_nodes:
                raise TreeBudgetExceeded("subagent tree total node limit")
            if (
                self.max_tokens
                and self.reserved_tokens + tokens > self.max_tokens
            ):
                raise TreeBudgetExceeded("subagent tree token budget exceeded")
            if self.max_usd and self.reserved_usd + usd > self.max_usd:
                raise TreeBudgetExceeded("subagent tree USD budget exceeded")
            self.active += 1
            self.nodes += 1
            self.reserved_tokens += tokens
            self.reserved_usd += usd
        return TreeBudgetLease(self, tokens, usd)

    def expired(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline


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
    for rec in store.list_runs(since=cutoff):
        ts = _parse(str(rec.get("at", "")))
        if ts is None or ts < cutoff:
            continue
        total += int((rec.get("usage") or {}).get("estTokens", 0) or 0)
    return total


# Anthropic list prices, USD per million tokens (published rates; update
# when they change). A birkin turn is mostly input — cached system prefix +
# history — so a blended estimate is stated as a range, not a single number.
LIST_PRICE_USD_PER_MTOK = {
    "opus": (15.0, 75.0),          # (input, output)
    "sonnet": (3.0, 15.0),
    "haiku": (0.80, 4.0),
}
# The metered Agent-SDK credit tiers Anthropic announced for 2026-06-15 and
# then paused. Kept here so `birkin budget` can answer "would this day have
# fit?" rather than the project having to argue about billing (ADR-050).
ANNOUNCED_CREDIT_TIERS_USD = {"pro": 20, "max5x": 100, "max20x": 200}


def _price_for(model: str) -> tuple[float, float]:
    name = (model or "").lower()
    for key, price in LIST_PRICE_USD_PER_MTOK.items():
        if key in name:
            return price
    return LIST_PRICE_USD_PER_MTOK["sonnet"]


def estimate_cost_usd(tokens: int, model: str,
                      output_fraction: float = 0.2) -> float:
    """What ``tokens`` would cost at API list rates for ``model``.

    An estimate, not a bill: the ledger records a single total per event, so
    the input/output split is assumed rather than measured.
    """
    inp, out = _price_for(model)
    tokens = max(0, int(tokens))
    frac = min(1.0, max(0.0, float(output_fraction)))
    blended = inp * (1.0 - frac) + out * frac
    return tokens / 1_000_000.0 * blended


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
    # to enforce, so skip the full ledger scan entirely — unlimited users
    # shouldn't pay a per-turn stat tax.
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
