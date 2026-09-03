"""Payload text with Unicode line separators must not split a journal record."""

from __future__ import annotations

from birkin import store
from birkin.approval_execution_journal import ExecutionJournal, authority_digest
from birkin.approval_execution_state import JournalPhase


def test_unicode_line_separators_in_payload_keep_the_journal_readable() -> None:
    # Given: an approval whose payload carries U+2028, U+2029 and U+0085,
    # none of which json.dumps(ensure_ascii=False) escapes.
    record = store.add_pending(
        category="office_create",
        title="separators",
        description="",
        payload={"paragraphs": ["first\u2028second\u2029third\u0085fourth"]},
        origin="test",
    )
    approval_id = str(record["id"])
    journal = ExecutionJournal(approval_id)

    # When: the journal is armed and advanced.
    journal.arm(
        authority_digest(record), "office_create", dict(record["payload"])
    )
    journal.ready()

    # Then: every event is still one record and the payload round-trips.
    snapshot = journal.load()
    assert snapshot.phase is JournalPhase.READY
    assert snapshot.payload == {
        "paragraphs": ["first\u2028second\u2029third\u0085fourth"]
    }
