"""Launch and recover one-shot approval helper processes."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any

from typing_extensions import assert_never

from . import config, procreg, store
from .approval_execution_codec import (
    JSONValue,
    JournalCodecError,
    parse_mapping,
)
from .approval_execution_events import drain_helper_stdout
from .approval_execution_helper import project_terminal
from .approval_execution_journal import (
    ExecutionJournal,
    JournalCorruptionError,
    authority_digest,
)
from .approval_execution_process import launch_helper
from .approval_execution_state import JournalPhase
from .approval_execution_types import EventSink


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
    on_event: EventSink | None = None,
) -> dict[str, JSONValue] | None:
    """Project terminal state, launch ready work, or freeze an unknown outcome."""
    path = config.pending_dir() / f"{approval_id}.json"
    process: subprocess.Popen[bytes] | None = None
    capture_events = wait and on_event is not None
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
                    process = launch_helper(journal, capture_stdout=capture_events)
                case JournalPhase.READY:
                    process = launch_helper(journal, capture_stdout=capture_events)
                case JournalPhase.HELPER_STARTED:
                    if not _owner_alive(
                        snapshot.owner_pid,
                        snapshot.owner_generation,
                    ):
                        process = launch_helper(
                            journal,
                            capture_stdout=capture_events,
                        )
                case JournalPhase.ATTEMPT_COMMITTED:
                    if not _owner_alive(
                        snapshot.owner_pid,
                        snapshot.owner_generation,
                    ):
                        if snapshot.category == "mail_send":
                            from .m365_graph import GraphError
                            from .m365_mail import reconcile_approved_send

                            try:
                                result = reconcile_approved_send(snapshot.payload)
                            except (GraphError, OSError):
                                journal.outcome_unknown()
                            else:
                                parsed = json.loads(result)
                                if isinstance(parsed, dict) and parsed.get("state") == "submitted":
                                    journal.succeeded(result)
                                else:
                                    journal.outcome_unknown()
                            project_terminal(approval_id, record, journal.load())
                        elif snapshot.category.startswith("office_"):
                            journal.resume_office()
                            process = launch_helper(
                                journal,
                                capture_stdout=capture_events,
                            )
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
    except store.FileLockTimeout:
        # FileLockTimeout subclasses TimeoutError -> OSError, so it must be
        # caught ahead of the freeze clause: contention (a second approver, a
        # concurrent recover_all, an antivirus scan) is retryable, not corrupt.
        return {"ok": False, "error": "approval store is busy", "retryable": True}
    except Exception as exc:
        # Every entry point calls recover_all() at startup, so nothing here may
        # escape: project_terminal() reaches office receipt code that raises
        # DocumentError (neither OSError nor JournalCorruptionError) whenever the
        # office job record is gone, which would kill chat, gateway and web with
        # a traceback. Freeze the one poisoned approval instead.
        _freeze(approval_id, str(exc))
        return {"ok": False, "error": str(exc)}
    if process is not None and wait:
        if on_event is not None and process.stdout is not None:
            drain_helper_stdout(process.stdout, on_event)
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
            return recover_one(approval_id, on_event=on_event)
        if return_code != 0:
            return {
                "ok": False,
                "error": f"approval helper exited with status {return_code}",
            }
        return recover_one(approval_id, on_event=on_event)
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


def recheck_unknown_mail_send(
    approval_id: str,
    *,
    client: Any = None,
) -> dict[str, JSONValue]:
    """Re-observe one terminal mail attempt without creating or sending mail."""
    if not store.valid_pending_id(approval_id):
        return {"ok": False, "error": "승인 ID가 올바르지 않습니다"}
    path = config.pending_dir() / f"{approval_id}.json"
    try:
        with store.file_lock(path):
            record = store.get_pending(approval_id)
            if record is None:
                return {"ok": False, "error": "승인 기록을 찾을 수 없습니다"}
            if (
                record.get("category") != "mail_send"
                or record.get("status") not in {
                    "action_outcome_unknown", "approved", "resume_pending",
                }
            ):
                return {"ok": False, "error": "재확인할 수 있는 메일 발송 기록이 아닙니다"}
            journal = ExecutionJournal(approval_id)
            try:
                snapshot = journal.load()
            except JournalCorruptionError as exc:
                _freeze(approval_id, str(exc))
                return {"ok": False, "error": "승인 실행 기록의 무결성을 확인할 수 없습니다"}
            if snapshot.category != "mail_send" or snapshot.authority_digest != authority_digest(record):
                _freeze(approval_id, "approval execution authority was changed")
                return {"ok": False, "error": "승인 실행 권한이 변경되었습니다"}
            checked_at = datetime.now(timezone.utc).isoformat()
            confirmed_result: object = None
            if snapshot.result is not None:
                try:
                    confirmed_result = json.loads(snapshot.result)
                except json.JSONDecodeError:
                    pass
            confirmed_submitted = (
                isinstance(confirmed_result, dict)
                and confirmed_result.get("state") == "submitted"
            )
            if (
                snapshot.phase is JournalPhase.SUCCEEDED
                and confirmed_submitted
                and record.get("status") in {
                    "action_outcome_unknown", "approved", "resume_pending",
                }
            ):
                previous_checked_at = record.get("mail_rechecked_at")
                if isinstance(previous_checked_at, str) and previous_checked_at:
                    checked_at = previous_checked_at
                if record.get("status") == "action_outcome_unknown":
                    project_terminal(approval_id, record, snapshot)
                current = store.get_pending(approval_id)
                if current is None or current.get("status") not in {"approved", "resume_pending"}:
                    return {"ok": False, "error": "확인된 발송 처리 결과를 반영할 수 없습니다"}
                _ = store.resolve_pending(
                    approval_id,
                    str(current["status"]),
                    updates={
                        "recheckable": False,
                        "mail_recheck_state": "submitted",
                        "mail_rechecked_at": checked_at,
                    },
                )
                return {
                    "ok": True,
                    "state": "submitted",
                    "recheckable": False,
                    "mail_rechecked_at": checked_at,
                    "message": "Microsoft 365 발송 처리가 확인되었습니다",
                }
            if snapshot.phase is JournalPhase.SUCCEEDED:
                return {"ok": False, "error": "재확인으로 확정된 발송 처리 기록이 아닙니다"}
            if (
                snapshot.phase is not JournalPhase.ACTION_OUTCOME_UNKNOWN
                or record.get("status") != "action_outcome_unknown"
            ):
                return {"ok": False, "error": "재확인할 수 있는 메일 발송 기록이 아닙니다"}
            if (
                record.get("mail_recheck_state") == "needs_review"
                or record.get("recheckable") is False
            ):
                result: dict[str, JSONValue] = {
                    "ok": True,
                    "state": "needs_review",
                    "recheckable": False,
                    "message": "연결 계정 또는 승인 내용을 확인할 수 없어 검토가 필요합니다",
                }
                previous_checked_at = record.get("mail_rechecked_at")
                if isinstance(previous_checked_at, str) and previous_checked_at:
                    result["mail_rechecked_at"] = previous_checked_at
                return result

            from .m365_graph import GraphError
            from .m365_mail import reconcile_approved_send

            try:
                result = reconcile_approved_send(snapshot.payload, client=client)
            except ValueError:
                state = "needs_review"
                recheckable = False
            except (GraphError, OSError):
                state = "unknown"
                recheckable = True
            else:
                parsed = json.loads(result)
                state = str(parsed.get("state") if isinstance(parsed, dict) else "unknown")
                recheckable = state not in {"submitted", "needs_review"}
                if state == "submitted":
                    journal.confirm_mail_succeeded(result)
                    project_terminal(approval_id, record, journal.load())
                    current = store.get_pending(approval_id)
                    if current is None:
                        return {"ok": False, "error": "확인된 발송 처리 결과를 반영할 수 없습니다"}
                    terminal_status = str(current.get("status") or "")
                    _ = store.resolve_pending(
                        approval_id,
                        terminal_status,
                        updates={
                            "recheckable": False,
                            "mail_recheck_state": "submitted",
                            "mail_rechecked_at": checked_at,
                        },
                    )
                    return {
                        "ok": True,
                        "state": "submitted",
                        "recheckable": False,
                        "mail_rechecked_at": checked_at,
                        "message": "Microsoft 365 발송 처리가 확인되었습니다",
                    }

            _ = store.resolve_pending(
                approval_id,
                "action_outcome_unknown",
                updates={
                    "recheckable": recheckable,
                    "mail_recheck_state": state,
                    "mail_rechecked_at": checked_at,
                },
            )
            messages = {
                "accepted": "Microsoft 365가 요청을 접수했지만 발송 처리는 아직 확인되지 않았습니다",
                "needs_review": "연결 계정 또는 승인 내용을 확인할 수 없어 검토가 필요합니다",
                "observed_non_draft": "원격 메일이 초안이 아님은 확인했지만 발송 시각은 확인되지 않았습니다",
            }
            return {
                "ok": True,
                "state": state,
                "recheckable": recheckable,
                "mail_rechecked_at": checked_at,
                "message": messages.get(state, "현재 원격 발송 상태를 확인할 수 없습니다"),
            }
    except store.FileLockTimeout:
        return {
            "ok": False,
            "error": "메일 발송 상태를 다른 작업에서 확인 중입니다",
            "retryable": True,
            "recheckable": True,
        }


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
