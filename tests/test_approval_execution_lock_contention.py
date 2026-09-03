"""Lock contention must stay retryable instead of freezing an approval."""

from __future__ import annotations

import threading

from birkin import approval_execution_recovery, config, store
from birkin.approval_execution_journal import ExecutionJournal, authority_digest


def _armed_execution() -> str:
    record = store.add_pending(
        category="memory",
        title="sealed",
        description="",
        payload={"value": "sealed"},
        origin="test",
    )
    approval_id = str(record["id"])
    _ = store.resolve_pending(approval_id, "executing")
    current = store.get_pending(approval_id)
    assert current is not None
    journal = ExecutionJournal(approval_id)
    journal.arm(authority_digest(current), "memory", {"value": "sealed"})
    journal.ready()
    return approval_id


def test_record_lock_contention_does_not_freeze_the_approval() -> None:
    # Given: an armed execution whose record lock another holder owns.
    approval_id = _armed_execution()
    path = config.pending_dir() / f"{approval_id}.json"
    held = threading.Event()
    release = threading.Event()

    def _hold() -> None:
        with store.file_lock(path, timeout=5.0):
            held.set()
            release.wait(30.0)

    holder = threading.Thread(target=_hold)
    holder.start()
    try:
        assert held.wait(5.0)

        # When: recovery runs while the lock is unavailable.
        result = approval_execution_recovery.recover_one(approval_id)
    finally:
        release.set()
        holder.join(10.0)

    # Then: it reports a retryable busy store and leaves the record alone.
    assert result == {
        "ok": False,
        "error": "approval store is busy",
        "retryable": True,
    }
    after = store.get_pending(approval_id)
    assert after is not None
    assert after["status"] == "executing"
    assert "execution_error" not in after
