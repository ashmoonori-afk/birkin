"""Risk tiers for approval-gated actions (P6).

Every proposal that flows through :mod:`birkin.approvals` carries a category
(``memory``, ``skill``, ``cron``, ``shell``, ...). A risk *tier* is a one-word
summary of how much damage the action could do if approved blindly — it does
*not* change whether the action is auto-approved (that's still controlled by
``config["auto_approve"]``), only how it's surfaced in the review inbox and
dashboard so the human can prioritize.

Tiers (lowest → highest):
- ``low``       — memory note or skill draft; reversible local file edit.
- ``medium``    — cron schedule registration; persistent but bounded.
- ``high``      — shell, Office mutation, checkpoint restore, or computer use;
  potentially broad local effect.
- ``critical``  — reserved for future use (e.g. outbound payments, deletes).

The mapping is intentionally short and explicit. New categories default to
``medium`` so unknown actions don't slip in as ``low``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

_RecordT = TypeVar("_RecordT", bound=Mapping[str, object])

TIERS = ("low", "medium", "high", "critical")
TIER_ORDER = {t: i for i, t in enumerate(TIERS)}

CATEGORY_RISK: dict[str, str] = {
    "memory": "low",
    "skill":  "low",
    "cron":   "medium",
    "work_item": "medium",
    "connection": "medium",
    "mail_send": "high",
    # A workflow spends tokens and time but writes nothing by itself;
    # its agents are text-only and every consequential act inside one
    # still hits its own gate.
    "moirai": "medium",
    # A harness prompt/subagent entry writes no files and runs nothing, but it
    # is injected into the system prompt of every later turn -- it steers what
    # the agent chooses to do, so it is reviewed with shell-level attention.
    "harness": "high",
    "shell":  "high",
    "operation": "high",
    "office_create": "high",
    "office_job": "high",
    "office_rollback": "high",
    "checkpoint_restore": "high",
    "computer_use": "high",
}


def risk_for(category: str) -> str:
    """Return the risk tier for a category; unknown categories default to medium."""
    return CATEGORY_RISK.get((category or "").strip().lower(), "medium")


def label(tier: str) -> str:
    """Pretty single-character tag for terminal output (no color dependency)."""
    return {"low": "·", "medium": "!", "high": "!!", "critical": "‼"}.get(tier, "?")


def sort_by_risk(
    records: list[_RecordT],
) -> list[_RecordT]:
    """Sort pending records highest-risk-first (stable within tier)."""
    def key(rec: Mapping[str, object]) -> int:
        value = rec.get("category")
        cat = value if isinstance(value, str) else ""
        return -TIER_ORDER.get(risk_for(cat), 1)
    return sorted(records, key=key)
