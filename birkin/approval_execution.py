"""Crash-safe approval claiming, one-shot execution, and continuation."""

from __future__ import annotations

from pathlib import Path

from . import config, store, worker_hooks
from .approval_execution_codec import JSONValue, JournalCodecError, parse_mapping
from .approval_execution_journal import (
    ExecutionJournal,
    JournalCorruptionError,
    authority_digest,
)
from .approval_execution_state import JournalPhase
from .approval_execution_types import ActionExecutor, EventSink

_OFFICE_CATEGORIES = frozenset({"office_create", "office_job", "office_rollback"})


def _pending_path(approval_id: str) -> Path:
    return config.pending_dir() / f"{approval_id}.json"


_authority_digest = authority_digest


def claim(
    approval_id: str,
    *,
    approved_by: str,
    approved_via: str,
) -> dict[str, JSONValue]:
    """Atomically claim pending approval authority."""
    if not approved_by.strip() or not approved_via.strip():
        raise ValueError("approval resolver identity must be non-empty")
    if not store.valid_pending_id(approval_id):
        return {"ok": False, "error": "invalid approval id"}
    try:
        with store.file_lock(_pending_path(approval_id)):
            record: dict[str, JSONValue] | None = store.get_pending(approval_id)
            if record is None or record.get("status") != "pending":
                return {"ok": False, "error": "not found or already resolved"}
            if record.get("action_state") == "action_needed":
                return {"ok": False, "error": "structured action requires answers"}
            if record.get("category") == "workflow":
                return {
                    "ok": False,
                    "error": "Telegram workflow requires its origin chat",
                }
            _ = store.resolve_pending(
                approval_id,
                "approving",
                approved_by=approved_by,
                approved_via=approved_via,
            )
    except store.FileLockTimeout:
        return {"ok": False, "error": "approval store is busy"}
    except OSError as exc:
        return {"ok": False, "error": f"approval store is unavailable: {exc}"}
    return {"ok": True}


def execute_claimed(
    approval_id: str,
    executor: ActionExecutor | None = None,
    on_event: EventSink | None = None,
) -> dict[str, JSONValue]:
    """Seal one claimed action, then invoke it through the helper boundary."""
    if not store.valid_pending_id(approval_id):
        return {"ok": False, "error": "invalid approval id"}
    try:
        with store.file_lock(_pending_path(approval_id)):
            record: dict[str, JSONValue] | None = store.get_pending(approval_id)
            if record is None or record.get("status") != "approving":
                return {"ok": False, "error": "approval is not claimed"}
            continuation = record.get("continuation")
            if continuation is not None:
                try:
                    _ = worker_hooks.validate(continuation)
                except worker_hooks.WorkerHookError as exc:
                    _ = store.resolve_pending(
                        approval_id,
                        "error",
                        updates={
                            "failure_stage": "validation",
                            "execution_error": str(exc),
                        },
                    )
                    return {"ok": False, "error": str(exc)}
            try:
                payload = parse_mapping(record.get("payload"))
            except (JournalCodecError, TypeError, ValueError):
                _ = store.resolve_pending(
                    approval_id,
                    "execution_frozen",
                    updates={"failure_stage": "journal_integrity"},
                )
                return {"ok": False, "error": "approval payload is malformed"}
            journal = ExecutionJournal(approval_id)
            if journal.path.exists():
                snapshot = journal.load()
                if (
                    snapshot.authority_digest != _authority_digest(record)
                    or snapshot.category != "cron"
                    or snapshot.phase is not JournalPhase.RETRYABLE_FAILURE
                ):
                    raise JournalCorruptionError(
                        "approval execution journal already spent its authority"
                    )
                journal.retry_cron()
            else:
                journal.arm(
                    _authority_digest(record),
                    str(record.get("category") or ""),
                    payload,
                )
                journal.ready()
            _ = store.resolve_pending(approval_id, "executing")
    except store.FileLockTimeout:
        return {"ok": False, "error": "approval store is busy"}
    except (OSError, JournalCorruptionError) as exc:
        return {"ok": False, "error": f"approval execution could not be armed: {exc}"}
    if executor is not None:
        from .approval_execution_injected import execute

        result = execute(approval_id, executor, on_event)
    else:
        from .approval_execution_recovery import recover_one

        result = recover_one(approval_id, wait=True) or {
            "ok": False,
            "error": "approval execution state is missing",
        }
    current: dict[str, JSONValue] | None = store.get_pending(approval_id)
    if (
        result.get("ok")
        and current is not None
        and current.get("status") == "resume_pending"
    ):
        continued = execute_continuation(approval_id, on_event=on_event)
        if continued.get("ok"):
            continued["result"] = result.get("result", "")
        return continued
    return result


def execute_continuation(
    approval_id: str,
    on_event: EventSink | None = None,
) -> dict[str, JSONValue]:
    if not store.valid_pending_id(approval_id):
        return {"ok": False, "error": "invalid approval id"}
    try:
        with store.file_lock(_pending_path(approval_id)):
            record: dict[str, JSONValue] | None = store.get_pending(approval_id)
            if record is None or record.get("status") != "resume_pending":
                return {"ok": False, "error": "continuation is not pending"}
            continuation = worker_hooks.validate(record.get("continuation"))
            _ = store.resolve_pending(approval_id, "resuming")
    except (OSError, store.FileLockTimeout, worker_hooks.WorkerHookError) as exc:
        return {"ok": False, "error": str(exc)}
    try:
        result = worker_hooks.dispatch(continuation, on_event=on_event)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        _ = store.resolve_pending(
            approval_id,
            "error",
            updates={"failure_stage": "continuation", "execution_error": str(exc)},
        )
        return {"ok": False, "error": f"continuation failed: {exc}"}
    _ = store.resolve_pending(
        approval_id,
        "approved",
        updates={"continuation_result": result},
    )
    _ = store.remove_action_receipt(approval_id)
    return {"ok": True, "continuation_result": result}


def restore_claim(approval_id: str) -> bool:
    if not store.valid_pending_id(approval_id):
        return False
    try:
        with store.file_lock(_pending_path(approval_id)):
            record: dict[str, JSONValue] | None = store.get_pending(approval_id)
            if record is None or record.get("status") != "approving":
                return False
            _ = store.resolve_pending(approval_id, "pending")
    except (OSError, store.FileLockTimeout):
        return False
    return True


def approve(
    approval_id: str,
    executor: ActionExecutor | None = None,
    on_event: EventSink | None = None,
    *,
    approved_by: str,
    approved_via: str,
) -> dict[str, JSONValue]:
    if not approved_by.strip() or not approved_via.strip():
        raise ValueError("approval resolver identity must be non-empty")
    current: dict[str, JSONValue] | None = store.get_pending(approval_id)
    if current is not None and current.get("status") == "executing":
        if (
            current.get("category") in _OFFICE_CATEGORIES
            and (not current.get("approved_by") or not current.get("approved_via"))
        ):
            return {"ok": False, "error": "Office approval authority is incomplete"}
        terminal_phases = {
            JournalPhase.SUCCEEDED,
            JournalPhase.FAILED,
            JournalPhase.RETRYABLE_FAILURE,
            JournalPhase.ACTION_OUTCOME_UNKNOWN,
        }
        try:
            phase = ExecutionJournal(approval_id).load().phase
        except JournalCorruptionError:
            phase = None
        recoverable = (
            current.get("category") in _OFFICE_CATEGORIES
            or phase is None
            or phase in terminal_phases
        )
        if recoverable:
            from .approval_execution_recovery import recover_one

            return recover_one(
                approval_id,
                wait=current.get("category") in _OFFICE_CATEGORIES,
            ) or {
                "ok": False,
                "error": "approval execution state is missing",
            }
    claimed = claim(
        approval_id,
        approved_by=approved_by,
        approved_via=approved_via,
    )
    if not claimed.get("ok"):
        return claimed
    return execute_claimed(approval_id, executor, on_event=on_event)


def reject(
    approval_id: str,
    reason: str = "",
    *,
    rejected_by: str,
    rejected_via: str,
) -> dict[str, JSONValue]:
    if not rejected_by.strip() or not rejected_via.strip():
        raise ValueError("rejection resolver identity must be non-empty")
    if not store.valid_pending_id(approval_id):
        return {"ok": False}
    try:
        with store.file_lock(_pending_path(approval_id)):
            record: dict[str, JSONValue] | None = store.get_pending(approval_id)
            if record is None or record.get("status") != "pending":
                return {"ok": False}
            _ = store.resolve_pending(
                approval_id,
                "rejected",
                reason=reason,
                rejected_by=rejected_by,
                rejected_via=rejected_via,
            )
    except (OSError, store.FileLockTimeout):
        return {"ok": False}
    return {"ok": True}
