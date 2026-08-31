from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from birkin import approval_execution, store


def _proposal() -> dict[str, object]:
    return store.add_pending(
        category="skill",
        title="Run exactly once",
        description="",
        payload={"proposal_digest": "a" * 64},
        origin="test",
    )


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
        first = approval_execution.approve(approval_id, executor)
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
    restarted = approval_execution.approve(approval_id, executor)

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
    first = approval_execution.approve(approval_id, executor)
    assert first["recoverable"] is True
    assert action_runs == 1

    changed = store.get_pending(approval_id)
    assert changed is not None
    changed["payload"] = {"proposal_digest": "b" * 64}
    _ = approval_path.write_text(json.dumps(changed), encoding="utf-8")
    contention_enabled = False

    restarted = approval_execution.approve(approval_id, executor)

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

    result = approval_execution.approve(approval_id, executor)

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
    result = approval_execution.approve(approval_id, executor, on_event=events.append)

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
        return approval_execution.approve(approval_id, executor)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(approve_at_once, range(20)))

    assert action_runs == 1
    assert sum(result.get("ok") is True for result in results) == 1
    approved = store.get_pending(approval_id)
    assert approved is not None
    assert approved["status"] == "approved"
    assert store.get_action_receipt(approval_id) is None
