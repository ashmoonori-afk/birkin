"""One journaled event per streamed chunk must not re-parse the whole log."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.workspace.journal import WorkspaceJournal


def _delta(journal: WorkspaceJournal, text: str) -> int:
    event = journal.append(
        "message.assistant.delta",
        actor_id="native",
        command_id="turn-1",
        payload={"text": text},
    )
    return event.cursor


def test_append_does_not_reparse_the_whole_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = WorkspaceJournal(tmp_path, "cost")
    for _ in range(3):
        _ = _delta(journal, "chunk")

    def _forbidden(_self: WorkspaceJournal) -> list[object]:
        raise AssertionError("append must not read the entire journal")

    monkeypatch.setattr(WorkspaceJournal, "_read_events", _forbidden)
    assert _delta(journal, "chunk") == 4
    monkeypatch.undo()
    assert [event.cursor for event in journal.events()] == [1, 2, 3, 4]


def test_next_cursor_comes_from_the_file_not_from_memory(tmp_path: Path) -> None:
    first = WorkspaceJournal(tmp_path, "cost")
    second = WorkspaceJournal(tmp_path, "cost")
    assert _delta(first, "a") == 1
    assert _delta(second, "b") == 2
    assert _delta(first, "c") == 3


def test_next_cursor_survives_an_event_larger_than_the_tail_window(
    tmp_path: Path,
) -> None:
    journal = WorkspaceJournal(tmp_path, "cost")
    assert _delta(journal, "small") == 1
    assert _delta(journal, "x" * 20_000) == 2
    assert _delta(journal, "small") == 3
    assert [event.cursor for event in journal.events()] == [1, 2, 3]
