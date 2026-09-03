"""Session ids name journal directories, so the mapping must stay injective."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.workspace.contracts import ProtocolError
from birkin.workspace.journal import WorkspaceJournal


def test_folding_session_ids_cannot_reach_another_journal(tmp_path: Path) -> None:
    journal = WorkspaceJournal(tmp_path, "alpha")
    _ = journal.append(
        "message.user",
        actor_id="web:view-1",
        command_id="c-1",
        payload={"text": "SECRET"},
    )

    for variant in ("Alpha", "ALPHA", "alpha.", "nul", "a:b"):
        with pytest.raises(ProtocolError, match="session_id"):
            _ = WorkspaceJournal(tmp_path, variant)

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["alpha"]
    assert len(journal.events()) == 1
