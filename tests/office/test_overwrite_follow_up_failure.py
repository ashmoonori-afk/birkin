"""A failing overwrite follow-up must land in the journal, not escape."""

from __future__ import annotations

import pytest

from birkin import store
from birkin.approval_execution_injected import execute
from birkin.approval_execution_journal import ExecutionJournal, authority_digest
from birkin.approval_execution_state import JournalPhase
from birkin.office import overwrite_retry
from birkin.office.errors import DocumentError, DocumentErrorCode


def _collision() -> DocumentError:
    return DocumentError(
        code=DocumentErrorCode.OUTPUT_EXISTS,
        stage="commit",
        message="output exists",
    )


def test_follow_up_failure_is_journalled(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: an office approval mid-attempt whose overwrite follow-up cannot be
    # queued (a rebound proposal that no longer matches its approval).
    record = store.add_pending(
        category="office_create",
        title="create",
        description="",
        payload={"destination": "out.docx"},
        origin="test",
    )
    approval_id = str(record["id"])
    _ = store.resolve_pending(approval_id, "executing")
    current = store.get_pending(approval_id)
    assert current is not None
    journal = ExecutionJournal(approval_id)
    journal.arm(authority_digest(current), "office_create", {"destination": "out.docx"})
    journal.ready()

    def _refuse(**_kwargs: object) -> dict[str, object]:
        raise DocumentError(
            code=DocumentErrorCode.POLICY_DENIED,
            stage="approval",
            message="overwrite follow-up changed the approved Office proposal",
        )

    monkeypatch.setattr(overwrite_retry, "queue_overwrite_follow_up", _refuse)

    def _executor(*_args: object, **_kwargs: object) -> str:
        raise _collision()

    # When: the action hits an output collision.
    result = execute(approval_id, _executor, None)

    # Then: nothing escapes, the journal is terminal, and the record is not
    # left executing for recover_all to resume forever.
    assert result["ok"] is False
    assert ExecutionJournal(approval_id).load().phase is JournalPhase.FAILED
    after = store.get_pending(approval_id)
    assert after is not None
    assert after["status"] == "error"
