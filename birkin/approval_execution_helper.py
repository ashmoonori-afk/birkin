"""One-shot process boundary for sealed approval actions."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from typing_extensions import assert_never

from . import approval_dispatch, config, procreg, store
from .approval_execution_codec import JSONValue
from .approval_execution_events import emit_event
from .approval_execution_journal import ExecutionJournal, JournalCorruptionError
from .approval_execution_journal import authority_digest
from .approval_execution_state import JournalPhase, JournalSnapshot
from .approval_execution_types import SealedApprovalId
from .office.errors import DocumentError, DocumentErrorCode

_EXIT_BEFORE_ATTEMPT = "before_attempt"
_EXIT_AFTER_EFFECT = "after_effect_before_receipt"
@dataclass(frozen=True, slots=True)
class _PreparedExecution:
    snapshot: JournalSnapshot
    record: dict[str, JSONValue]


def helper_argv(
    approval_id: str,
    owner_token: str,
    *,
    executable: str,
    frozen: bool,
) -> tuple[str, ...]:
    """Build shell-free argv for source and frozen Birkin entry points."""
    if frozen:
        return (executable, "_approval-helper", approval_id, owner_token)
    return (executable, "-m", "birkin", "_approval-helper", approval_id, owner_token)


def run(approval_id: str, owner_token: str) -> int:
    """Own one approval until its attempt receives a durable outcome."""
    if not store.valid_pending_id(approval_id):
        return 2
    path = config.pending_dir() / f"{approval_id}.json"
    try:
        with store.file_lock(path, timeout=30.0):
            prepared = _prepare_locked(approval_id, owner_token)
        match prepared:
            case int() as return_code:
                return return_code
            case _PreparedExecution(snapshot=snapshot, record=record):
                pass
            case unreachable:
                assert_never(unreachable)
        journal = ExecutionJournal(approval_id)
        sealed_approval_id = SealedApprovalId(snapshot.approval_id)
        try:
            result = approval_dispatch.execute_action(
                snapshot.category,
                snapshot.payload,
                approval_dispatch.DispatchOptions(
                    cfg=config.load_config(),
                    on_event=emit_event,
                    office_approval_id=sealed_approval_id,
                ),
            )
        except store.FileLockTimeout as exc:
            with store.file_lock(path, timeout=30.0):
                if snapshot.category == "cron":
                    journal.retryable_cron_failure(str(exc))
                else:
                    journal.failed(str(exc))
                project_terminal(approval_id, record, journal.load())
            return 1
        except DocumentError as exc:
            with store.file_lock(path, timeout=30.0):
                if (
                    exc.code is DocumentErrorCode.OUTPUT_EXISTS
                    and snapshot.category in {"office_create", "office_job"}
                ):
                    from .office.overwrite_retry import queue_overwrite_follow_up

                    follow_up = queue_overwrite_follow_up(
                        approval_id=approval_id,
                        category=snapshot.category,
                        payload=snapshot.payload,
                    )
                    _ = store.resolve_pending(
                        approval_id,
                        "executing",
                        updates={
                            "failure_code": exc.code.value,
                            "follow_up_approval_id": str(follow_up["id"]),
                        },
                    )
                    journal.failed(str(exc))
                    project_terminal(approval_id, record, journal.load())
                elif exc.retryable and snapshot.category.startswith("office_"):
                    return 1
                else:
                    journal.failed(str(exc))
                    project_terminal(approval_id, record, journal.load())
            return 1
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            with store.file_lock(path, timeout=30.0):
                journal.failed(str(exc))
                project_terminal(approval_id, record, journal.load())
            return 1
        if os.environ.get("BIRKIN_APPROVAL_HELPER_TEST_EXIT") == _EXIT_AFTER_EFFECT:
            os._exit(87)
        with store.file_lock(path, timeout=30.0):
            journal.succeeded(result)
            project_terminal(approval_id, record, journal.load())
        return 0
    except store.FileLockTimeout:
        return 3
    except JournalCorruptionError:
        return 4
    except OSError as exc:
        _freeze(approval_id, f"approval execution durability failed: {exc}")
        return 5


def _prepare_locked(
    approval_id: str,
    owner_token: str,
) -> _PreparedExecution | int:
    journal = ExecutionJournal(approval_id)
    snapshot = journal.load()
    record: dict[str, JSONValue] | None = store.get_pending(approval_id)
    if (
        record is None
        or snapshot.approval_id != approval_id
        or snapshot.authority_digest != authority_digest(record)
    ):
        _freeze(approval_id, "sealed approval authority differs from its journal")
        return 4
    match snapshot.phase:
        case JournalPhase.READY:
            pass
        case JournalPhase.HELPER_STARTED:
            if snapshot.owner_token != owner_token:
                return 0
            journal.helper_started(
                owner_pid=os.getpid(),
                owner_token=owner_token,
                owner_generation=procreg.process_generation(os.getpid()),
            )
        case JournalPhase.ATTEMPT_COMMITTED:
            if snapshot.owner_token != owner_token:
                return 0
        case (
            JournalPhase.SUCCEEDED
            | JournalPhase.FAILED
            | JournalPhase.RETRYABLE_FAILURE
            | JournalPhase.ACTION_OUTCOME_UNKNOWN
        ):
            project_terminal(approval_id, record, snapshot)
            return 0
        case JournalPhase.ARMED:
            return 0
        case _:
            assert_never(snapshot.phase)
    if os.environ.get("BIRKIN_APPROVAL_HELPER_TEST_EXIT") == _EXIT_BEFORE_ATTEMPT:
        os._exit(86)
    if snapshot.phase is not JournalPhase.ATTEMPT_COMMITTED:
        journal.commit_attempt(
            owner_pid=os.getpid(),
            owner_token=owner_token,
            owner_generation=procreg.process_generation(os.getpid()),
        )
    return _PreparedExecution(snapshot=snapshot, record=record)


def _durable_result(snapshot: JournalSnapshot) -> str | None:
    match snapshot.category:
        case "office_job":
            from .office.coordinator_recovery import approved_office_receipt

            return approved_office_receipt(snapshot.payload)
        case "office_create":
            from .office.create_execution import approved_creation_receipt

            return approved_creation_receipt(snapshot.payload)
        case _:
            return snapshot.result


def _write_receipt(
    record: Mapping[str, JSONValue],
    snapshot: JournalSnapshot,
    result: str,
) -> None:
    approval_id = str(record["id"])
    store.write_action_receipt(
        approval_id,
        {
            "version": 1,
            "status": "action_committed",
            "approval_id": approval_id,
            "authority_digest": snapshot.authority_digest,
            "result": result,
        },
    )


def project_terminal(
    approval_id: str,
    record: Mapping[str, JSONValue],
    snapshot: JournalSnapshot,
) -> None:
    match snapshot.phase:
        case JournalPhase.SUCCEEDED:
            result = _durable_result(snapshot)
            if result is None:
                _freeze(approval_id, "successful execution has no result")
                return
            _write_receipt(record, snapshot, result)
            status = (
                "resume_pending"
                if record.get("continuation") is not None
                else "approved"
            )
            _ = store.resolve_pending(
                approval_id,
                status,
                updates={"action_receipt": result},
            )
            _ = store.remove_action_receipt(approval_id)
        case JournalPhase.FAILED:
            _ = store.resolve_pending(
                approval_id,
                "error",
                updates={
                    "failure_stage": "action",
                    "execution_error": snapshot.error or "action failed",
                },
            )
        case JournalPhase.RETRYABLE_FAILURE:
            _ = store.resolve_pending(
                approval_id,
                "pending",
                updates={"execution_error": snapshot.error or "cron store is busy"},
            )
        case JournalPhase.ACTION_OUTCOME_UNKNOWN:
            _ = store.resolve_pending(
                approval_id,
                "action_outcome_unknown",
                updates={"failure_stage": "action_outcome_unknown"},
            )
        case (
            JournalPhase.ARMED
            | JournalPhase.READY
            | JournalPhase.HELPER_STARTED
            | JournalPhase.ATTEMPT_COMMITTED
        ):
            return
        case _:
            assert_never(snapshot.phase)


def _freeze(approval_id: str, reason: str) -> None:
    _ = store.resolve_pending(
        approval_id,
        "execution_frozen",
        updates={
            "failure_stage": "journal_integrity",
            "execution_error": reason[:2000],
        },
    )
