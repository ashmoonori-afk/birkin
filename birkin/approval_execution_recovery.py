"""Launch and recover one-shot approval helper processes."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys

from typing_extensions import assert_never

from . import config, procreg, store
from .approval_execution_codec import JSONValue, JournalCodecError, parse_mapping
from .approval_execution_helper import helper_argv, project_terminal
from .approval_execution_journal import (
    ExecutionJournal,
    JournalCorruptionError,
    authority_digest,
)
from .approval_execution_state import JournalPhase


def recover_all() -> list[str]:
    """Recover every durable approval execution without replaying an attempt."""
    recovered: list[str] = []
    identifiers = {
        path.name.removesuffix(".execution.jsonl")
        for path in config.pending_dir().glob("*.execution.jsonl")
    }
    for path in config.pending_dir().glob("*.json"):
        if path.name.endswith(".receipt.json"):
            continue
        record: dict[str, JSONValue] | None = store.get_pending(path.stem)
        if record is not None and record.get("status") in {"approving", "executing"}:
            identifiers.add(path.stem)
    for approval_id in sorted(identifiers):
        if recover_one(approval_id) is not None:
            recovered.append(approval_id)
    return recovered


def recover_one(
    approval_id: str,
    *,
    wait: bool = False,
) -> dict[str, JSONValue] | None:
    """Project terminal state, launch ready work, or freeze an unknown outcome."""
    path = config.pending_dir() / f"{approval_id}.json"
    process: subprocess.Popen[bytes] | None = None
    try:
        with store.file_lock(path):
            record: dict[str, JSONValue] | None = store.get_pending(approval_id)
            if record is None:
                return None
            if record.get("status") == "execution_frozen":
                return {
                    "ok": False,
                    "error": str(record.get("execution_error") or "execution frozen"),
                }
            journal = ExecutionJournal(approval_id)
            if not journal.path.exists() and _migrate_legacy(journal, record):
                return {"ok": True, "status": "pending"}
            try:
                snapshot = journal.load()
            except JournalCorruptionError as exc:
                _freeze(approval_id, str(exc))
                return {"ok": False, "error": str(exc)}
            if snapshot.authority_digest != authority_digest(record):
                _freeze(approval_id, "approval execution authority was changed")
                return {
                    "ok": False,
                    "error": "approval execution authority was changed",
                }
            match snapshot.phase:
                case JournalPhase.ARMED:
                    journal.ready()
                    _ = store.resolve_pending(approval_id, "executing")
                    process = _launch(journal)
                case JournalPhase.READY:
                    process = _launch(journal)
                case JournalPhase.HELPER_STARTED:
                    if not _owner_alive(
                        snapshot.owner_pid,
                        snapshot.owner_generation,
                    ):
                        process = _launch(journal)
                case JournalPhase.ATTEMPT_COMMITTED:
                    if not _owner_alive(
                        snapshot.owner_pid,
                        snapshot.owner_generation,
                    ):
                        if snapshot.category.startswith("office_"):
                            journal.resume_office()
                            process = _launch(journal)
                        else:
                            journal.outcome_unknown()
                            project_terminal(approval_id, record, journal.load())
                case (
                    JournalPhase.SUCCEEDED
                    | JournalPhase.FAILED
                    | JournalPhase.RETRYABLE_FAILURE
                    | JournalPhase.ACTION_OUTCOME_UNKNOWN
                ):
                    project_terminal(approval_id, record, snapshot)
                case _:
                    assert_never(snapshot.phase)
    except (OSError, store.FileLockTimeout, JournalCorruptionError) as exc:
        _freeze(approval_id, str(exc))
        return {"ok": False, "error": str(exc)}
    if process is not None and wait:
        return_code = process.wait()
        try:
            phase = ExecutionJournal(approval_id).load().phase
        except JournalCorruptionError:
            phase = None
        if phase in {
            JournalPhase.SUCCEEDED,
            JournalPhase.FAILED,
            JournalPhase.RETRYABLE_FAILURE,
            JournalPhase.ACTION_OUTCOME_UNKNOWN,
        }:
            return recover_one(approval_id)
        if return_code != 0:
            return {
                "ok": False,
                "error": f"approval helper exited with status {return_code}",
            }
        return recover_one(approval_id)
    current: dict[str, JSONValue] | None = store.get_pending(approval_id)
    if current is None:
        return None
    status = str(current.get("status") or "")
    if status in {"approved", "resume_pending"}:
        return {"ok": True, "result": str(current.get("action_receipt") or "")}
    if status == "error":
        detail = str(current.get("execution_error") or "unknown error")
        follow_up_approval_id = current.get("follow_up_approval_id")
        if isinstance(follow_up_approval_id, str):
            from .office.overwrite_retry import OVERWRITE_QUESTION

            return {
                "ok": False,
                "error": OVERWRITE_QUESTION,
                "follow_up_approval_id": follow_up_approval_id,
            }
        error = (
            detail
            if detail.startswith("action failed:")
            else f"action failed: {detail}"
        )
        return {"ok": False, "error": error}
    if (
        status == "pending"
        and ExecutionJournal(approval_id).load().phase is JournalPhase.RETRYABLE_FAILURE
    ):
        return {
            "ok": False,
            "error": str(current.get("execution_error") or "cron store is busy"),
        }
    if status == "action_outcome_unknown":
        return {"ok": False, "error": "action outcome is unknown", "recoverable": False}
    if status == "execution_frozen":
        return {
            "ok": False,
            "error": str(current.get("execution_error") or "execution frozen"),
        }
    return {"ok": True, "status": status}


def _launch(journal: ExecutionJournal) -> subprocess.Popen[bytes]:
    owner_token = secrets.token_hex(32)
    command = helper_argv(
        journal.approval_id,
        owner_token,
        executable=sys.executable,
        frozen=bool(getattr(sys, "frozen", False)),
    )
    if os.name == "nt":
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_BREAKAWAY_FROM_JOB
            ),
        )
    else:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
            start_new_session=True,
        )
    try:
        journal.helper_started(
            owner_pid=process.pid,
            owner_token=owner_token,
            owner_generation=procreg.process_generation(process.pid),
        )
    except (OSError, JournalCorruptionError):
        process.kill()
        _ = process.wait()
        raise
    return process


def _owner_alive(pid: int | None, generation: str | None) -> bool:
    if pid is None or generation is None or not procreg.pid_alive(pid):
        return False
    return procreg.process_generation(pid) == generation


def _migrate_legacy(
    journal: ExecutionJournal,
    record: dict[str, JSONValue],
) -> bool:
    status = record.get("status")
    if status == "approving":
        _ = store.resolve_pending(journal.approval_id, "pending")
        return True
    if status != "executing":
        raise JournalCorruptionError("approval execution journal is missing")
    try:
        payload = parse_mapping(record.get("payload"))
    except (JournalCodecError, TypeError, ValueError) as exc:
        raise JournalCorruptionError("legacy approval payload is malformed") from exc
    journal.arm(
        authority_digest(record),
        str(record.get("category") or ""),
        payload,
    )
    journal.ready()
    if record.get("category") == "office_job":
        return False
    receipt = store.get_action_receipt(journal.approval_id)
    result = receipt.get("result") if receipt is not None else None
    digest = receipt.get("authority_digest") if receipt is not None else None
    journal.commit_attempt(owner_pid=0)
    if isinstance(result, str) and digest == authority_digest(record):
        journal.succeeded(result)
    else:
        journal.outcome_unknown()
    project_terminal(journal.approval_id, record, journal.load())
    return False


def _freeze(approval_id: str, reason: str) -> None:
    try:
        _ = store.resolve_pending(
            approval_id,
            "execution_frozen",
            updates={
                "failure_stage": "journal_integrity",
                "execution_error": reason[:2000],
            },
        )
    except OSError:
        return
