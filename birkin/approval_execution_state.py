"""Typed state reconstruction for approval execution journal events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .approval_execution_codec import JSONValue


class JournalPhase(str, Enum):
    ARMED = "armed"
    READY = "ready"
    HELPER_STARTED = "helper_started"
    ATTEMPT_COMMITTED = "attempt_committed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYABLE_FAILURE = "retryable_failure"
    ACTION_OUTCOME_UNKNOWN = "action_outcome_unknown"


class JournalStateError(RuntimeError):
    """Journal events do not describe a legal execution state."""


@dataclass(frozen=True, slots=True)
class JournalSnapshot:
    approval_id: str
    authority_digest: str
    category: str
    payload: dict[str, JSONValue]
    phase: JournalPhase
    owner_pid: int | None = None
    owner_token: str | None = None
    owner_generation: str | None = None
    result: str | None = None
    error: str | None = None


def snapshot(events: list[dict[str, JSONValue]]) -> JournalSnapshot:
    first = events[0] if events else None
    if first is None or first.get("kind") != JournalPhase.ARMED.value:
        raise JournalStateError("approval execution journal is not armed")
    authority = first.get("authority_digest")
    category = first.get("category")
    payload = first.get("payload")
    if (
        not isinstance(authority, str)
        or not isinstance(category, str)
        or not isinstance(payload, dict)
    ):
        raise JournalStateError("approval execution authority is malformed")
    allowed = {
        JournalPhase.ARMED: None,
        JournalPhase.READY: JournalPhase.ARMED,
        JournalPhase.HELPER_STARTED: JournalPhase.READY,
        JournalPhase.ATTEMPT_COMMITTED: JournalPhase.HELPER_STARTED,
        JournalPhase.SUCCEEDED: JournalPhase.ATTEMPT_COMMITTED,
        JournalPhase.FAILED: JournalPhase.ATTEMPT_COMMITTED,
        JournalPhase.RETRYABLE_FAILURE: JournalPhase.ATTEMPT_COMMITTED,
        JournalPhase.ACTION_OUTCOME_UNKNOWN: JournalPhase.ATTEMPT_COMMITTED,
    }
    phase = JournalPhase.ARMED
    for event in events[1:]:
        try:
            candidate = JournalPhase(str(event.get("kind")))
        except ValueError as exc:
            raise JournalStateError("approval execution phase is invalid") from exc
        transition_valid = allowed[candidate] is phase
        if candidate is JournalPhase.READY and (
            (
                phase is JournalPhase.ATTEMPT_COMMITTED
                and category.startswith("office_")
            )
            or (phase is JournalPhase.RETRYABLE_FAILURE and category == "cron")
        ):
            transition_valid = True
        if (
            candidate is JournalPhase.HELPER_STARTED
            and phase is JournalPhase.HELPER_STARTED
        ):
            transition_valid = True
        if candidate is JournalPhase.ATTEMPT_COMMITTED and phase is JournalPhase.READY:
            transition_valid = True
        if not transition_valid:
            raise JournalStateError("approval execution transitions are invalid")
        phase = candidate
    tail = events[-1]
    owner_pid = tail.get("owner_pid")
    owner_token = tail.get("owner_token")
    owner_generation = tail.get("owner_generation")
    result = tail.get("result")
    error = tail.get("error")
    return JournalSnapshot(
        approval_id=str(first["approval_id"]),
        authority_digest=authority,
        category=category,
        payload=payload,
        phase=phase,
        owner_pid=owner_pid if isinstance(owner_pid, int) else None,
        owner_token=owner_token if isinstance(owner_token, str) else None,
        owner_generation=(
            owner_generation if isinstance(owner_generation, str) else None
        ),
        result=result if isinstance(result, str) else None,
        error=error if isinstance(error, str) else None,
    )
