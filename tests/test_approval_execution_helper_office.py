from __future__ import annotations

from pathlib import Path

import pytest

from birkin import store
from birkin.approval_execution_journal import ExecutionJournal
from birkin.approval_execution_state import JournalPhase
from tests.native_office_support import approved_docx


def test_helper_dispatch_preserves_sealed_office_approval_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the native Office jail is the configured Birkin home.
    office_home = tmp_path / "office"
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    # When: canonical Office approval executes through the real helper process.
    artifact = approved_docx(office_home)

    # Then: the helper consumes the same journal-bound approval inside the jail.
    journals = list((tmp_path / "pending").glob("*.execution.jsonl"))
    assert len(journals) == 1
    approval_id = journals[0].name.removesuffix(".execution.jsonl")
    record = store.get_pending(approval_id)
    assert record is not None
    assert record["status"] == "approved"
    snapshot = ExecutionJournal(approval_id).load()
    assert snapshot.approval_id == approval_id
    assert snapshot.phase is JournalPhase.SUCCEEDED
    assert Path(str(artifact["uri"])).is_relative_to(office_home)
