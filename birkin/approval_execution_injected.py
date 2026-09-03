"""Typed in-process seam for deterministic approval executor tests."""

from __future__ import annotations

import os

from . import config, procreg, store
from .approval_execution_codec import JSONValue, parse_mapping
from .approval_execution_journal import ExecutionJournal, JournalCorruptionError
from .approval_execution_state import JournalPhase
from .approval_execution_types import ActionExecutor, EventSink
from .office.errors import DocumentError, DocumentErrorCode


def execute(
    approval_id: str,
    executor: ActionExecutor,
    on_event: EventSink | None,
) -> dict[str, JSONValue]:
    """Invoke an injected executor under the production journal contract."""
    from .approval_execution_helper import project_terminal

    path = config.pending_dir() / f"{approval_id}.json"
    journal = ExecutionJournal(approval_id)
    try:
        with store.file_lock(path):
            journal.commit_attempt(
                owner_pid=os.getpid(),
                owner_generation=procreg.process_generation(os.getpid()),
            )
            record: dict[str, JSONValue] | None = store.get_pending(approval_id)
    except store.FileLockTimeout:
        return {"ok": False, "error": "approval store is busy"}
    if record is None:
        return {"ok": False, "error": "approval execution state is missing"}
    category = str(record.get("category") or "")
    payload = parse_mapping(record.get("payload"))
    try:
        if category.startswith("office_"):
            result = executor(
                category,
                payload,
                {"_office_approval_id": approval_id},
                on_event=on_event,
            )
        elif on_event is not None:
            result = executor(category, payload, on_event=on_event)
        else:
            result = executor(category, payload)
    except store.FileLockTimeout as exc:
        if category == "cron":
            try:
                with store.file_lock(path):
                    current = store.get_pending(approval_id)
                    if current is None or current.get("status") != "executing":
                        return {"ok": False, "error": "approval store is busy"}
                    journal.retryable_cron_failure(str(exc))
                    project_terminal(approval_id, current, journal.load())
            except store.FileLockTimeout:
                return {"ok": False, "error": "approval store is busy"}
            return {"ok": False, "error": str(exc)}
        return _persist_failure(approval_id, journal, exc)
    except DocumentError as exc:
        if (
            exc.code is DocumentErrorCode.OUTPUT_EXISTS
            and category in {"office_create", "office_job"}
        ):
            from .office.overwrite_retry import (
                OVERWRITE_QUESTION,
                queue_overwrite_follow_up,
            )

            try:
                follow_up = queue_overwrite_follow_up(
                    approval_id=approval_id,
                    category=category,
                    payload=payload,
                )
            except Exception as follow_up_exc:
                # Queueing can fail (a rebound proposal that no longer matches).
                # Record the failure instead of escaping, or recover_all resumes
                # this approval on every start.
                return _persist_failure(approval_id, journal, follow_up_exc)
            try:
                with store.file_lock(path):
                    _ = store.resolve_pending(
                        approval_id,
                        "executing",
                        updates={
                            "failure_code": exc.code.value,
                            "follow_up_approval_id": str(follow_up["id"]),
                        },
                    )
                    journal.failed(str(exc))
                    current = store.get_pending(approval_id)
                    if current is not None:
                        project_terminal(approval_id, current, journal.load())
            except store.FileLockTimeout:
                return {"ok": False, "error": "approval store is busy"}
            return {
                "ok": False,
                "error": OVERWRITE_QUESTION,
                "follow_up_approval_id": str(follow_up["id"]),
            }
        if exc.retryable and category.startswith("office_"):
            journal.resume_office()
            return {"ok": False, "error": f"action recovery required: {exc}"}
        return _persist_failure(approval_id, journal, exc)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _persist_failure(approval_id, journal, exc)
    try:
        with store.file_lock(path):
            journal.succeeded(result)
            project_terminal(approval_id, record, journal.load())
    except (OSError, store.FileLockTimeout, JournalCorruptionError) as exc:
        return _persist_failure(approval_id, journal, exc)
    return {
        "ok": True,
        "result": result if category.startswith("office_") else result[:2000],
    }


def _persist_failure(
    approval_id: str,
    journal: ExecutionJournal,
    exc: Exception,
) -> dict[str, JSONValue]:
    from .approval_execution_helper import project_terminal

    path = config.pending_dir() / f"{approval_id}.json"
    try:
        with store.file_lock(path):
            phase = journal.load().phase
            if phase is JournalPhase.SUCCEEDED:
                return {
                    "ok": False,
                    "error": f"action committed; approval finalization is pending: {exc}",
                    "recoverable": True,
                    "result": journal.load().result or "",
                }
            if phase is JournalPhase.ATTEMPT_COMMITTED:
                journal.failed(str(exc))
                current = store.get_pending(approval_id)
                if current is not None:
                    project_terminal(approval_id, current, journal.load())
    except (OSError, store.FileLockTimeout, JournalCorruptionError):
        return {"ok": False, "error": f"action outcome persistence failed: {exc}"}
    return {"ok": False, "error": f"action failed: {exc}"}
