"""UI state contract: the single source of truth for state semantics.

Every Birkin surface (REPL, /dash, WebUI) renders runtime work through the
nine states below. Raw runtime statuses are mapped here and only here; a
status this module does not recognize becomes ``unknown`` — surfaces never
invent states. Non-Python surfaces consume :func:`schema` (JSON Schema) and
must not hand-copy these tables.

Encoding is quad-redundant (glyph + ascii + label + color role) so state
remains legible under NO_COLOR, ASCII-only terminals, and color blindness.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

UI_STATES: tuple[str, ...] = (
    "running", "waiting_human", "waiting_dependency", "idle", "paused",
    "completed", "failed", "expired", "unknown")

# Attention-first ordering: what needs a human outranks what is broken,
# which outranks what we cannot reason about, which outranks live work.
# Resolved work always sinks to the bottom.
_ATTENTION: dict[str, int] = {
    "waiting_human": 0, "failed": 1, "expired": 2, "unknown": 3,
    "running": 4, "waiting_dependency": 5, "paused": 6, "idle": 7,
    "completed": 8,
}

#            state                glyph  ascii  label       color role
_ENCODING: dict[str, tuple[str, str, str, str]] = {
    "running":            ("▸", ">", "실행중",   "running"),
    "waiting_human":      ("◆", "!", "응답대기", "waiting_human"),
    "waiting_dependency": ("◇", "o", "의존대기", "waiting_dependency"),
    "idle":               ("·", ".", "유휴",     "muted"),
    "paused":             ("∥", "=", "일시정지", "muted"),
    "completed":          ("✓", "+", "완료",     "success"),
    "failed":             ("✗", "x", "실패",     "failure"),
    "expired":            ("⊘", "*", "만료",     "warning"),
    "unknown":            ("?", "?", "불명",     "warning"),
}


@dataclass(frozen=True)
class StateView:
    """One unit of work seen through the contract."""

    state: str
    raw: str
    domain: str


def attention_rank(state: str) -> int:
    """Sort key: lower = needs the user sooner."""
    return _ATTENTION.get(state, _ATTENTION["unknown"])


def glyph(state: str, *, ascii_only: bool = False) -> str:
    enc = _ENCODING.get(state) or _ENCODING["unknown"]
    return enc[1] if ascii_only else enc[0]


def label(state: str) -> str:
    return (_ENCODING.get(state) or _ENCODING["unknown"])[2]


def color_role(state: str) -> str:
    return (_ENCODING.get(state) or _ENCODING["unknown"])[3]


def _view(mapping: dict[str, str], raw: str, domain: str) -> StateView:
    return StateView(mapping.get(raw, "unknown"), raw, domain)


# -- approvals (store.py pending records) -----------------------------------

_APPROVAL: dict[str, str] = {
    "pending": "waiting_human",
    "claimed": "running", "approving": "running", "executing": "running",
    "resuming": "running",
    "resume_pending": "waiting_dependency",
    "approved": "completed", "completed": "completed", "rejected": "completed",
    "error": "failed",
    "expired": "expired",
    # interrupted work is resumable, not dead
    "interrupted": "paused",
}


def from_approval(record: dict[str, Any]) -> StateView:
    """Map a pending-approval record; a lapsed expiry beats ``pending``."""
    raw = str(record.get("status", ""))
    if raw == "pending":
        expires_at = record.get("expires_at")
        if expires_at:
            try:
                limit = datetime.fromisoformat(str(expires_at))
            except ValueError:
                limit = None
            if (limit is not None and limit.tzinfo is not None
                    and limit <= datetime.now(timezone.utc)):
                return StateView("expired", raw, "approval")
    return _view(_APPROVAL, raw, "approval")


# -- background jobs (background_receipts.JobStatus) ------------------------

_JOB: dict[str, str] = {
    "queued": "waiting_dependency", "running": "running",
    "succeeded": "completed", "failed": "failed",
    # a deliberate, non-resumable stop is a resolution, not an error
    "cancelled": "completed",
}


def from_job(status: str) -> StateView:
    return _view(_JOB, str(status), "job")


def from_cron(*, enabled: bool) -> StateView:
    """Map a scheduled cron definition into the shared UI state."""
    raw = "enabled" if enabled else "disabled"
    state = "idle" if enabled else "paused"
    return StateView(state, raw, "cron")


def from_recent_run(record: dict[str, Any]) -> StateView:
    """Map a persisted run, surfacing its only authoritative error signal."""
    details = record.get("details")
    error = details.get("error") if isinstance(details, dict) else None
    state = "failed" if error else "completed"
    return StateView(state, "error" if error else "completed", "recent_run")


# -- durable subagent runs (agentruns._STATUSES) ----------------------------

_AGENT_RUN: dict[str, str] = {
    "running": "running", "done": "completed", "error": "failed",
    # heartbeat lost: we genuinely do not know; never guess liveness
    "stale": "unknown",
}


def from_agent_run(status: str) -> StateView:
    return _view(_AGENT_RUN, str(status), "agent_run")


# -- session goals (goals._STATUSES) ----------------------------------------

_GOAL: dict[str, str] = {
    "active": "running", "paused": "paused", "done": "completed",
}


def from_goal(status: str) -> StateView:
    return _view(_GOAL, str(status), "goal")


# -- moirai journal calls ---------------------------------------------------

_MOIRAI: dict[str, str] = {
    "running": "running", "completed": "completed", "error": "failed",
    # aborted runs hit a cap or an abort flag: work did not finish
    "aborted": "failed",
}


def from_moirai(status: str) -> StateView:
    return _view(_MOIRAI, str(status), "moirai")


# -- schema export ----------------------------------------------------------

def schema() -> dict[str, Any]:
    """JSON Schema consumed by non-Python surfaces (WebUI, tooling).

    ``x-birkin-encoding`` carries the presentation contract so a TypeScript
    client can generate its state table instead of hand-copying it.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://birkin.local/schema/uistate.json",
        "title": "BirkinUIState",
        "type": "object",
        "properties": {
            "state": {"type": "string", "enum": list(UI_STATES)},
            "raw": {"type": "string"},
            "domain": {"type": "string"},
        },
        "required": ["state"],
        "x-birkin-encoding": {
            s: {
                "glyph": glyph(s),
                "ascii": glyph(s, ascii_only=True),
                "label": label(s),
                "color_role": color_role(s),
                "attention": attention_rank(s),
            }
            for s in UI_STATES
        },
    }
