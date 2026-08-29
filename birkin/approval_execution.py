"""Atomic approval claiming, execution, continuation, and recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from . import config, store, worker_hooks

_OFFICE_CATEGORIES = frozenset({"office_job", "office_rollback"})


class ActionExecutor(Protocol):
    def __call__(
        self,
        category: str,
        payload: dict[str, Any],
        cfg: dict[str, Any] | None = None,
        on_event: Any = None,
    ) -> str: ...


def _pending_path(approval_id: str) -> Path:
    return config.pending_dir() / f"{approval_id}.json"


def claim(
    approval_id: str,
    *,
    approved_by: str,
    approved_via: str,
) -> dict[str, Any]:
    """Atomically claim pending authority or re-enter an Office recovery."""
    if not store.valid_pending_id(approval_id):
        return {"ok": False, "error": "invalid approval id"}
    try:
        with store.file_lock(_pending_path(approval_id)):
            record = store.get_pending(approval_id)
            if not record:
                return {"ok": False, "error": "not found or already resolved"}
            resuming_office = (
                record.get("status") == "executing"
                and record.get("category") in _OFFICE_CATEGORIES
            )
            if resuming_office:
                if not record.get("approved_by") or not record.get("approved_via"):
                    return {
                        "ok": False,
                        "error": "Office approval authority is incomplete",
                    }
                return {"ok": True}
            if record.get("status") != "pending":
                return {"ok": False, "error": "not found or already resolved"}
            if record.get("action_state") == "action_needed":
                return {"ok": False, "error": "structured action requires answers"}
            if record.get("category") == "workflow":
                return {
                    "ok": False,
                    "error": "Telegram workflow requires its origin chat",
                }
            store.resolve_pending(
                approval_id,
                "approving",
                approved_by=approved_by,
                approved_via=approved_via,
            )
    except store.FileLockTimeout:
        return {"ok": False, "error": "approval store is busy"}
    return {"ok": True}


def execute_claimed(
    approval_id: str,
    executor: ActionExecutor,
    on_event: Any = None,
) -> dict[str, Any]:
    """Execute one claimed action and preserve recoverable Office authority."""
    if not store.valid_pending_id(approval_id):
        return {"ok": False, "error": "invalid approval id"}
    try:
        with store.file_lock(_pending_path(approval_id)):
            record = store.get_pending(approval_id)
            if not record:
                return {"ok": False, "error": "approval is not claimed"}
            resuming_office = (
                record.get("status") == "executing"
                and record.get("category") in _OFFICE_CATEGORIES
            )
            if record.get("status") != "approving" and not resuming_office:
                return {"ok": False, "error": "approval is not claimed"}
            continuation = record.get("continuation")
            if resuming_office and continuation is not None:
                return {
                    "ok": False,
                    "error": "Office approval cannot resume a continuation",
                }
            if not resuming_office:
                if continuation is not None:
                    try:
                        worker_hooks.validate(continuation)
                    except worker_hooks.WorkerHookError as exc:
                        store.resolve_pending(
                            approval_id,
                            "error",
                            updates={"failure_stage": "validation"},
                        )
                        return {"ok": False, "error": str(exc)}
                store.resolve_pending(approval_id, "executing")
    except store.FileLockTimeout:
        return {"ok": False, "error": "approval store is busy"}
    try:
        if record["category"] in _OFFICE_CATEGORIES:
            result = executor(
                record["category"],
                record.get("payload", {}),
                {"_office_approval_id": approval_id},
                on_event=on_event,
            )
        elif on_event is not None:
            result = executor(
                record["category"], record.get("payload", {}), on_event=on_event
            )
        else:
            result = executor(record["category"], record.get("payload", {}))
    except store.FileLockTimeout:
        if record["category"] in _OFFICE_CATEGORIES:
            return {"ok": False, "error": "Office job is already executing"}
        try:
            with store.file_lock(_pending_path(approval_id)):
                current = store.get_pending(approval_id)
                if not current or current.get("status") != "executing":
                    return {"ok": False, "error": "approval store is busy"}
                store.resolve_pending(approval_id, "pending")
        except store.FileLockTimeout:
            return {"ok": False, "error": "approval store is busy"}
        return {"ok": False, "error": "cron store is busy; retry."}
    except Exception as exc:
        if record["category"] in _OFFICE_CATEGORIES:
            from .office.errors import DocumentError

            match exc:
                case DocumentError(retryable=True):
                    return {
                        "ok": False,
                        "error": f"action recovery required: {exc}",
                    }
                case _:
                    pass
        store.resolve_pending(
            approval_id, "error", updates={"failure_stage": "action"}
        )
        return {"ok": False, "error": f"action failed: {exc}"}
    if continuation is not None:
        store.resolve_pending(
            approval_id, "resume_pending", updates={"action_receipt": result}
        )
        resumed = execute_continuation(approval_id, on_event=on_event)
        if resumed.get("ok"):
            resumed["result"] = result
        return resumed
    store.resolve_pending(
        approval_id, "approved", updates={"action_receipt": result}
    )
    return {"ok": True, "result": result}


def execute_continuation(
    approval_id: str, on_event: Any = None
) -> dict[str, Any]:
    if not store.valid_pending_id(approval_id):
        return {"ok": False, "error": "invalid approval id"}
    try:
        with store.file_lock(_pending_path(approval_id)):
            record = store.get_pending(approval_id)
            if not record or record.get("status") != "resume_pending":
                return {"ok": False, "error": "continuation is not pending"}
            continuation = worker_hooks.validate(record.get("continuation"))
            store.resolve_pending(approval_id, "resuming")
    except (store.FileLockTimeout, worker_hooks.WorkerHookError) as exc:
        return {"ok": False, "error": str(exc)}
    try:
        result = worker_hooks.dispatch(continuation, on_event=on_event)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        store.resolve_pending(
            approval_id, "error", updates={"failure_stage": "continuation"}
        )
        return {"ok": False, "error": f"continuation failed: {exc}"}
    store.resolve_pending(
        approval_id, "approved", updates={"continuation_result": result}
    )
    return {"ok": True, "continuation_result": result}


def restore_claim(approval_id: str) -> bool:
    if not store.valid_pending_id(approval_id):
        return False
    try:
        with store.file_lock(_pending_path(approval_id)):
            record = store.get_pending(approval_id)
            if not record or record.get("status") != "approving":
                return False
            store.resolve_pending(approval_id, "pending")
    except store.FileLockTimeout:
        return False
    return True


def approve(
    approval_id: str,
    executor: ActionExecutor,
    on_event: Any = None,
    *,
    approved_by: str,
    approved_via: str,
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    if not store.valid_pending_id(approval_id):
        return {"ok": False}
    try:
        with store.file_lock(_pending_path(approval_id)):
            record = store.get_pending(approval_id)
            if not record or record.get("status") != "pending":
                return {"ok": False}
            store.resolve_pending(
                approval_id,
                "rejected",
                reason=reason,
                rejected_by=rejected_by,
                rejected_via=rejected_via,
            )
    except store.FileLockTimeout:
        return {"ok": False}
    return {"ok": True}
