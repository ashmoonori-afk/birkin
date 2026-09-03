from __future__ import annotations

from pathlib import Path

import pytest

from birkin import store
from birkin.approval_execution_journal import ExecutionJournal, authority_digest
from birkin.approval_execution_recovery import recover_all

_JOB_ID = "0" * 32


def test_recover_all_freezes_office_approval_with_missing_creation_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a helper died between journal.succeeded() and resolve_pending(), and
    # the office job record for that approval was later purged by retention.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    record = store.add_pending(
        category="office_create",
        title="Create one document",
        description="",
        payload={"job_id": _JOB_ID},
        origin="test",
    )
    approval_id = str(record["id"])
    journal = ExecutionJournal(approval_id)
    journal.arm(authority_digest(record), "office_create", {"job_id": _JOB_ID})
    journal.ready()
    journal.commit_attempt(owner_pid=0)
    journal.succeeded("durable office result")
    _ = store.resolve_pending(approval_id, "executing")

    # When: an entry point runs startup recovery over the pending directory.
    recovered = recover_all()

    # Then: the unusable receipt freezes that one approval instead of raising
    # DocumentError out of every startup path.
    assert recovered == [approval_id]
    frozen = store.get_pending(approval_id)
    assert frozen is not None
    assert frozen["status"] == "execution_frozen"
    assert "durable creation receipt is unavailable" in str(frozen["execution_error"])
