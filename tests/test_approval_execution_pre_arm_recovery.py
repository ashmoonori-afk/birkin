from __future__ import annotations

from pathlib import Path

import pytest

from birkin import approval_execution, approval_execution_recovery, store
from birkin.approval_execution_codec import JSONValue
from birkin.approval_execution_journal import ExecutionJournal
from birkin.approval_execution_state import JournalPhase
from birkin.approval_execution_types import EventSink


def test_pre_arm_crash_restores_usable_pending_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: approval authority was claimed, but no journal or attempt was armed.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    _ = store.add_pending(
        category="skill",
        title="Run exactly once after recovery",
        description="",
        payload={"proposal_digest": "a" * 64},
        origin="test",
    )
    approval_id = next((tmp_path / "pending").glob("*.json")).stem
    action_runs = 0

    def executor(
        category: str,
        payload: dict[str, JSONValue],
        cfg: dict[str, JSONValue] | None = None,
        on_event: EventSink | None = None,
    ) -> str:
        nonlocal action_runs
        del category, payload, cfg, on_event
        action_runs += 1
        return "restored action result"

    assert approval_execution.claim(approval_id) == {"ok": True}
    journal = ExecutionJournal(approval_id)
    assert not journal.path.exists()

    # When: startup recovery observes the crash before journal arming.
    recovered_pre_arm = approval_execution_recovery.recover_one(approval_id)

    # Then: pending authority is restored without freezing or invoking the action.
    assert recovered_pre_arm == {"ok": True, "status": "pending"}
    restored = store.get_pending(approval_id)
    assert restored is not None
    assert restored["status"] == "pending"
    assert not journal.path.exists()
    assert action_runs == 0

    # When: the restored authority is reclaimed and executed through the real seam.
    assert approval_execution.claim(approval_id) == {"ok": True}
    executed = approval_execution.execute_claimed(approval_id, executor)
    recovered_terminal = approval_execution_recovery.recover_one(approval_id)

    # Then: execution succeeds and terminal recovery never replays the effect.
    assert executed == {"ok": True, "result": "restored action result"}
    assert recovered_terminal == {"ok": True, "result": "restored action result"}
    assert action_runs == 1
    assert journal.load().phase is JournalPhase.SUCCEEDED
