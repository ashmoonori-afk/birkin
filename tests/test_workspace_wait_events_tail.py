"""wait_events must not re-parse the journal while holding the condition."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.workspace.contracts import WorkspaceCommand
from birkin.workspace.hub import WorkspaceHub
from birkin.workspace.journal import WorkspaceJournal
from birkin.workspace.records import WorkspaceEvent


def _chat_command(cursor: int) -> WorkspaceCommand:
    return WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": "wait-tail-1",
            "expected_cursor": cursor,
            "type": "chat.send",
            "payload": {"text": "hello"},
            "client_context": {"surface": "terminal", "view_id": "local"},
        }
    )


def test_wait_events_predicate_does_not_parse_the_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = WorkspaceHub(
        root=tmp_path,
        handlers={"chat.send": lambda _payload: {"reply": "ok"}},
    )
    session, _ = hub.create("wait-tail")
    try:
        _ = session.submit(_chat_command(0), actor_id="tester")
        settled = session.wait_events(
            after=0,
            until="command.completed",
            timeout=5.0,
        )
        assert any(event.type == "command.completed" for event in settled)

        reads: list[int] = []
        original = WorkspaceJournal._read_events

        def counting(journal: WorkspaceJournal) -> list[WorkspaceEvent]:
            reads.append(1)
            return original(journal)

        monkeypatch.setattr(WorkspaceJournal, "_read_events", counting)

        pending = session.wait_events(after=0, until=None, timeout=0.2)
        assert pending == settled
        assert len(reads) == 1

        idle = session.wait_events(
            after=settled[-1].cursor,
            until=None,
            timeout=0.2,
        )
        assert idle == ()
        assert len(reads) == 1
    finally:
        hub.close()
