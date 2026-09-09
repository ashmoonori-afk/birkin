from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from birkin import approval_execution, approval_execution_recovery, store
from birkin.approval_execution_journal import (
    ExecutionJournal,
    JournalCorruptionError,
    authority_digest,
)
from birkin.approval_execution_helper import project_terminal
from birkin.approval_execution_state import JournalPhase


def _proposal() -> dict[str, object]:
    return store.add_pending(
        category="skill",
        title="Run exactly once",
        description="",
        payload={"proposal_digest": "a" * 64},
        origin="test",
    )


def _unknown_mail(
    continuation: dict[str, object] | None = None,
) -> tuple[str, ExecutionJournal]:
    proposal = store.add_pending(
        category="mail_send", title="Send", description="",
        payload={"draft_id": "d" * 32, "content_sha256": "a" * 64}, origin="test",
        continuation=continuation,
    )
    approval_id = str(proposal["id"])
    journal = ExecutionJournal(approval_id)
    journal.arm(authority_digest(proposal), "mail_send", proposal["payload"])
    journal.ready()
    journal.helper_started(owner_pid=1)
    journal.commit_attempt(owner_pid=1)
    journal.outcome_unknown()
    _ = store.resolve_pending(approval_id, "action_outcome_unknown")
    return approval_id, journal


def test_manual_mail_recheck_confirms_submitted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _unknown_mail()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "birkin.m365_mail.reconcile_approved_send",
        lambda payload, client=None: calls.append(dict(payload)) or '{"state":"submitted"}',
    )

    first = approval_execution_recovery.recheck_unknown_mail_send(approval_id)
    second = approval_execution_recovery.recheck_unknown_mail_send(approval_id)

    assert first["state"] == second["state"] == "submitted"
    assert first["mail_rechecked_at"] == second["mail_rechecked_at"]
    assert first["message"] == "Microsoft 365 발송 처리가 확인되었습니다"
    assert calls == [{"draft_id": "d" * 32, "content_sha256": "a" * 64}]
    assert journal.load().phase is JournalPhase.SUCCEEDED
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "approved"
    assert record["mail_recheck_state"] == "submitted"


@pytest.mark.parametrize(("state", "recheckable"), [("accepted", True), ("unknown", True), ("needs_review", False)])
def test_manual_mail_recheck_preserves_unconfirmed_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, recheckable: bool,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _unknown_mail()
    monkeypatch.setattr(
        "birkin.m365_mail.reconcile_approved_send",
        lambda payload, client=None: json.dumps({"state": state}),
    )

    result = approval_execution_recovery.recheck_unknown_mail_send(approval_id)

    assert result["state"] == state and result["recheckable"] is recheckable
    assert journal.load().phase is JournalPhase.ACTION_OUTCOME_UNKNOWN
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "action_outcome_unknown"
    assert record["mail_recheck_state"] == state


def test_only_unknown_mail_journal_can_be_confirmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = _proposal()
    approval_id = str(proposal["id"])
    journal = ExecutionJournal(approval_id)
    journal.arm(authority_digest(proposal), "skill", proposal["payload"])
    journal.ready()
    journal.helper_started(owner_pid=1)
    journal.commit_attempt(owner_pid=1)
    journal.outcome_unknown()

    with pytest.raises(JournalCorruptionError, match="unknown mail"):
        journal.confirm_mail_succeeded("result")
    journal._append({"kind": "succeeded", "result": "forged"})
    with pytest.raises(JournalCorruptionError, match="transitions"):
        journal.load()

    mail_id, mail_journal = _unknown_mail()
    assert mail_id != approval_id
    with pytest.raises(JournalCorruptionError, match="unknown mail"):
        mail_journal.confirm_mail_succeeded('{"state":"accepted"}')
    mail_journal._append({"kind": "succeeded", "result": '{"state":"accepted"}'})
    with pytest.raises(JournalCorruptionError, match="transitions"):
        mail_journal.load()


def test_repeated_mail_recheck_keeps_authority_and_can_later_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _unknown_mail()
    states = iter(("accepted", "submitted"))
    monkeypatch.setattr(
        "birkin.m365_mail.reconcile_approved_send",
        lambda payload, client=None: json.dumps({"state": next(states)}),
    )

    first = approval_execution_recovery.recheck_unknown_mail_send(approval_id)
    second = approval_execution_recovery.recheck_unknown_mail_send(approval_id)

    assert first["state"] == "accepted" and second["state"] == "submitted"
    assert journal.load().phase is JournalPhase.SUCCEEDED
    assert store.get_pending(approval_id)["status"] == "approved"


def test_manual_mail_recheck_recovers_crash_after_success_journal_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _unknown_mail()
    journal.confirm_mail_succeeded('{"state":"submitted"}')
    monkeypatch.setattr(
        "birkin.m365_mail.reconcile_approved_send",
        lambda payload, client=None: pytest.fail("confirmed journal must not query Graph"),
    )

    result = approval_execution_recovery.recheck_unknown_mail_send(approval_id)

    assert result["state"] == "submitted"
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "approved"
    assert record["mail_recheck_state"] == "submitted"


def test_manual_mail_recheck_recovers_crash_after_terminal_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _unknown_mail()
    journal.confirm_mail_succeeded('{"state":"submitted"}')
    record = store.get_pending(approval_id)
    assert record is not None
    project_terminal(approval_id, record, journal.load())
    monkeypatch.setattr(
        "birkin.m365_mail.reconcile_approved_send",
        lambda payload, client=None: pytest.fail("projected success must not query Graph"),
    )

    result = approval_execution_recovery.recheck_unknown_mail_send(approval_id)

    assert result["state"] == "submitted"
    projected = store.get_pending(approval_id)
    assert projected is not None and projected["status"] == "approved"
    assert projected["mail_recheck_state"] == "submitted"


def test_manual_mail_recheck_preserves_continuation_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, _journal = _unknown_mail({"session_id": "session-1"})
    monkeypatch.setattr(
        "birkin.m365_mail.reconcile_approved_send",
        lambda payload, client=None: '{"state":"submitted"}',
    )

    result = approval_execution_recovery.recheck_unknown_mail_send(approval_id)

    assert result["state"] == "submitted"
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "resume_pending"
    assert record["mail_recheck_state"] == "submitted"


def test_manual_mail_recheck_rejects_invalid_id_before_lock_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    result = approval_execution_recovery.recheck_unknown_mail_send("../outside")

    assert result == {"ok": False, "error": "승인 ID가 올바르지 않습니다"}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("category", "status"),
    [("skill", "action_outcome_unknown"), ("mail_send", "pending")],
)
def test_manual_mail_recheck_rejects_ineligible_record_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, category: str, status: str,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = store.add_pending(
        category=category, title="Pending", description="",
        payload={"draft_id": "d" * 32, "content_sha256": "a" * 64}, origin="test",
    )
    approval_id = str(proposal["id"])
    if status != "pending":
        _ = store.resolve_pending(approval_id, status)
    before = store.get_pending(approval_id)
    monkeypatch.setattr(
        "birkin.m365_mail.reconcile_approved_send",
        lambda payload, client=None: pytest.fail("ineligible record must not query Graph"),
    )

    result = approval_execution_recovery.recheck_unknown_mail_send(approval_id)

    assert result == {"ok": False, "error": "재확인할 수 있는 메일 발송 기록이 아닙니다"}
    assert store.get_pending(approval_id) == before
    assert not ExecutionJournal(approval_id).path.exists()


def test_concurrent_manual_mail_rechecks_observe_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _unknown_mail()
    calls = 0
    call_lock = threading.Lock()

    def reconcile(payload: object, client: object = None) -> str:
        nonlocal calls
        del payload, client
        with call_lock:
            calls += 1
        return '{"state":"submitted"}'

    monkeypatch.setattr("birkin.m365_mail.reconcile_approved_send", reconcile)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: approval_execution_recovery.recheck_unknown_mail_send(approval_id),
            range(2),
        ))

    assert [result["state"] for result in results] == ["submitted", "submitted"]
    assert calls == 1
    assert journal.load().phase is JournalPhase.SUCCEEDED


def test_mail_attempt_recovery_only_reconciles_existing_remote_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = store.add_pending(
        category="mail_send", title="Send", description="",
        payload={"draft_id": "d" * 32, "content_sha256": "a" * 64}, origin="test",
    )
    approval_id = str(proposal["id"])
    assert approval_execution.claim(
        approval_id, approved_by="human:test", approved_via="test",
    ) == {"ok": True}
    record = store.get_pending(approval_id)
    assert record is not None
    journal = ExecutionJournal(approval_id)
    journal.arm(authority_digest(record), "mail_send", record["payload"])
    journal.ready()
    journal.helper_started(owner_pid=999_999, owner_token="dead")
    journal.commit_attempt(owner_pid=999_999, owner_token="dead")
    _ = store.resolve_pending(approval_id, "executing")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "birkin.m365_mail.reconcile_approved_send",
        lambda payload: calls.append(dict(payload)) or '{"state": "submitted"}',
    )

    recovered = approval_execution_recovery.recover_one(approval_id)

    assert recovered == {"ok": True, "result": '{"state": "submitted"}'}
    assert calls == [{"draft_id": "d" * 32, "content_sha256": "a" * 64}]


def test_final_replace_contention_recovers_without_reexecuting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = _proposal()
    approval_id = str(proposal["id"])
    approval_path = tmp_path / "pending" / f"{approval_id}.json"
    action_runs = 0
    contention_enabled = True
    real_replace = os.replace

    def contended_replace(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> None:
        if contention_enabled and Path(destination) == approval_path:
            staged = json.loads(Path(source).read_text(encoding="utf-8"))
            if staged.get("status") == "approved":
                raise PermissionError("forced Windows destination handle contention")
        real_replace(source, destination)

    def executor(
        category: str,
        payload: dict[str, Any],
        cfg: dict[str, Any] | None = None,
        on_event: Any = None,
    ) -> str:
        nonlocal action_runs
        del cfg, on_event
        action_runs += 1
        assert category == "skill"
        assert payload == {"proposal_digest": "a" * 64}
        return "durable action result"

    monkeypatch.setattr(os, "replace", contended_replace)

    first_error: OSError | None = None
    try:
        first = approval_execution.approve(approval_id, executor, approved_by="human:test", approved_via="test")
    except OSError as exc:
        first_error = exc
        first = {"ok": False, "error": str(exc)}

    # Runtime evidence for the production race: the side effect happened once,
    # but Windows denied the terminal state replacement.
    assert action_runs == 1
    executing = store.get_pending(approval_id)
    assert executing is not None
    assert executing["status"] == "executing"
    assert first_error is None, first
    assert first["ok"] is False
    assert first["recoverable"] is True
    receipt_path = tmp_path / "pending" / f"{approval_id}.receipt.json"
    assert receipt_path.is_file()
    recoverable_receipt = store.get_action_receipt(approval_id)
    assert recoverable_receipt is not None
    assert recoverable_receipt["status"] == "action_committed"

    # Toggle the injected destination contention off and simulate a restarted
    # approval surface using only durable disk state.
    contention_enabled = False
    restarted = approval_execution.approve(approval_id, executor, approved_by="human:test", approved_via="test")

    assert restarted == {"ok": True, "result": "durable action result"}
    assert action_runs == 1
    record = store.get_pending(approval_id)
    assert record is not None
    assert record["status"] == "approved"
    assert record["action_receipt"] == "durable action result"
    assert store.get_action_receipt(approval_id) is None
    assert not receipt_path.exists()


def test_recovery_receipt_cannot_finalize_changed_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = _proposal()
    approval_id = str(proposal["id"])
    approval_path = tmp_path / "pending" / f"{approval_id}.json"
    action_runs = 0
    contention_enabled = True
    real_replace = os.replace

    def contended_replace(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> None:
        if contention_enabled and Path(destination) == approval_path:
            staged = json.loads(Path(source).read_text(encoding="utf-8"))
            if staged.get("status") == "approved":
                raise PermissionError("forced final replacement contention")
        real_replace(source, destination)

    def executor(
        category: str,
        payload: dict[str, Any],
        cfg: dict[str, Any] | None = None,
        on_event: Any = None,
    ) -> str:
        nonlocal action_runs
        del category, payload, cfg, on_event
        action_runs += 1
        return "committed"

    monkeypatch.setattr(os, "replace", contended_replace)
    first = approval_execution.approve(approval_id, executor, approved_by="human:test", approved_via="test")
    assert first["recoverable"] is True
    assert action_runs == 1

    changed = store.get_pending(approval_id)
    assert changed is not None
    changed["payload"] = {"proposal_digest": "b" * 64}
    _ = approval_path.write_text(json.dumps(changed), encoding="utf-8")
    contention_enabled = False

    restarted = approval_execution.approve(approval_id, executor, approved_by="human:test", approved_via="test")

    assert restarted == {
        "ok": False,
        "error": "approval execution authority was changed",
    }
    assert action_runs == 1
    frozen = store.get_pending(approval_id)
    assert frozen is not None
    assert frozen["status"] == "execution_frozen"
    assert store.get_action_receipt(approval_id) is not None


def test_orphan_receipt_cannot_skip_a_pending_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = _proposal()
    approval_id = str(proposal["id"])
    store.write_action_receipt(
        approval_id,
        {
            "version": 1,
            "status": "action_committed",
            "approval_id": approval_id,
            "authority_digest": approval_execution._authority_digest(proposal),
            "result": "forged orphan result",
        },
    )
    action_runs = 0

    def executor(
        category: str,
        payload: dict[str, Any],
        cfg: dict[str, Any] | None = None,
        on_event: Any = None,
    ) -> str:
        nonlocal action_runs
        del category, payload, cfg, on_event
        action_runs += 1
        return "real result"

    result = approval_execution.approve(approval_id, executor, approved_by="human:test", approved_via="test")

    assert result == {"ok": True, "result": "real result"}
    assert action_runs == 1
    assert store.get_action_receipt(approval_id) is None
    approved = store.get_pending(approval_id)
    assert approved is not None
    assert approved["action_receipt"] == "real result"


def test_continuation_terminal_state_removes_action_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = store.add_pending(
        category="skill",
        title="Continue after action",
        description="",
        payload={"proposal_digest": "e" * 64},
        origin="odyssey",
        continuation={
            "schema": 1,
            "handler": "worker.resume.v1",
            "worker": "odyssey",
            "context": {"checkpoint": "receipt-cleanup"},
        },
    )
    approval_id = str(proposal["id"])

    def executor(
        category: str,
        payload: dict[str, Any],
        cfg: dict[str, Any] | None = None,
        on_event: Any = None,
    ) -> str:
        del category, payload, cfg, on_event
        return "action result"

    events: list[dict[str, Any]] = []
    result = approval_execution.approve(approval_id, executor, on_event=events.append, approved_by="human:test", approved_via="test")

    assert result["ok"] is True
    assert result["result"] == "action result"
    assert result["continuation_result"] == ("resumed odyssey at receipt-cleanup")
    assert events == [
        {
            "type": "worker_resume",
            "worker": "odyssey",
            "context": {"checkpoint": "receipt-cleanup"},
        }
    ]
    assert store.get_action_receipt(approval_id) is None
    approved = store.get_pending(approval_id)
    assert approved is not None
    assert approved["status"] == "approved"
    assert approved["action_receipt"] == "action result"


def test_twenty_concurrent_approvers_execute_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = _proposal()
    approval_id = str(proposal["id"])
    start = threading.Barrier(20)
    runs_lock = threading.Lock()
    action_runs = 0

    def executor(
        category: str,
        payload: dict[str, Any],
        cfg: dict[str, Any] | None = None,
        on_event: Any = None,
    ) -> str:
        nonlocal action_runs
        del category, payload, cfg, on_event
        with runs_lock:
            action_runs += 1
        return "done"

    def approve_at_once(_index: int) -> dict[str, Any]:
        _ = start.wait(timeout=10)
        return approval_execution.approve(approval_id, executor, approved_by="human:test", approved_via="test")

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(approve_at_once, range(20)))

    assert action_runs == 1
    assert sum(result.get("ok") is True for result in results) == 1
    approved = store.get_pending(approval_id)
    assert approved is not None
    assert approved["status"] == "approved"
    assert store.get_action_receipt(approval_id) is None
