"""A one-line status line, reprinted at each turn boundary.

birkin's main surface is a scrolling REPL, so a *pinned* status bar can't be
fixed without fighting the scrollback (the plan rejects it). The line-flow
translation is to reprint a DIM one-liner after every assistant turn (and on
``/status``): identity first, then context, then the volatile/actionable state
at the right — tmux's status-left / window / status-right ordering.

Segments are self-hiding (starship conditional modules): a segment that would
carry no news is omitted, so its mere appearance is the signal. Everything is
wired to real backend data — model/provider from config, daemon from the
on-disk heartbeat, budget from budget.status, pending from the approvals
inbox — nothing is invented.

Color-safe truncation: variable-length fields (the model id) are cut with
ui.fit() on the *plain* value before being wrapped in SGR, so a cut never lands
inside an escape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import ui


def _k(n: int) -> str:
    """Humanize a token count: 82000 -> '82k', 1400000 -> '1.4M'."""
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _hhmm(iso: Any) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def build(cfg: dict[str, Any], *, model_cap: int = 22) -> str:
    """Return the DIM status line for ``cfg`` (already color-gated via ui.*)."""
    C, D, G, Y, R, RST = ui.CYAN, ui.DIM, ui.GREEN, ui.YELLOW, ui.RED, ui.RESET
    left: list[str] = []
    right: list[str] = []

    # -- identity (always shown) ------------------------------------------
    model = ui.fit(str(cfg.get("model") or "?"), model_cap)
    provider = ui.fit(str(cfg.get("provider") or "?"), 12)
    left.append(f"{C}{model}{RST}{D}·{provider}{RST}")

    # -- daemon (context) — only speak up when it has run -----------------
    try:
        from . import store
        st = store.read_status()
        stale = store.is_status_stale(st)
    except Exception:
        st, stale = {}, False
    if st.get("daemon") or st.get("heartbeat"):
        if st.get("daemon") and not stale:
            left.append(f"{G}●up{RST}")
        elif stale:
            left.append(f"{Y}◐stale{RST}")
        else:
            left.append(f"{D}○down{RST}")
    nm = _hhmm(st.get("next_morpheus") or st.get("next_nightly"))
    if nm:
        left.append(f"{D}morpheus {nm}{RST}")

    # -- budget (volatile, right) — token counts, never dollars -----------
    try:
        from . import budget
        b = budget.status(cfg)
        cap = int(b.get("daily_cap") or 0)
        used = int(b.get("used_today") or 0)
        if cap > 0:
            frac = used / cap
            col = R if b.get("over_daily") else ui.severity(frac, 0.0, 0.8, 1.0)
            right.append(f"{col}tok {_k(used)}/{_k(cap)} {ui.bar(frac, 6)}{RST}")
        elif used > 0:
            right.append(f"{D}tok {_k(used)}{RST}")
    except Exception:
        pass

    # -- pending approvals (most actionable, far right) -------------------
    try:
        from . import approvals
        n = len(approvals.reviewable_pending())
        if n:
            right.append(f"{R}⚑{n}{RST}")
    except Exception:
        pass

    sep = f"{D} · {RST}"
    return sep.join(left + right)


def render(cfg: dict[str, Any]) -> str:
    """The status line with a leading two-space gutter, ready to print."""
    return "  " + build(cfg)
