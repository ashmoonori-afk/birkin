from __future__ import annotations

from pathlib import Path

from birkin.workspace import WorkspaceCommand, WorkspaceHub


def _command(
    command_type: str,
    command_id: str,
    cursor: int,
    payload: dict[str, object],
) -> WorkspaceCommand:
    return WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": command_id,
            "expected_cursor": cursor,
            "type": command_type,
            "payload": payload,
            "client_context": {"surface": "macos", "view_id": "main"},
        }
    )


def test_session_select_records_event_and_changes_snapshot(tmp_path: Path) -> None:
    hub = WorkspaceHub(root=tmp_path, handlers={"chat.send": lambda _p: {}})
    first, _ = hub.create("first")
    _second, _ = hub.create("second")
    before = hub.snapshot()

    receipt = hub.select(
        _command("session.select", "select-1", before.cursor, {"session_id": "second"}),
        actor_id="macos:main",
    )

    assert receipt.state == "completed"
    assert hub.snapshot().session_id == "second"
    assert any(
        event.type == "session.selected"
        and event.payload == {"session_id": "second"}
        for event in first.events()
    )
    hub.close()


def test_session_rename_updates_canonical_summaries(tmp_path: Path) -> None:
    hub = WorkspaceHub(root=tmp_path, handlers={"chat.send": lambda _p: {}})
    session, _ = hub.create("first")

    receipt = hub.rename(
        _command(
            "session.rename",
            "rename-1",
            session.snapshot().cursor,
            {"session_id": "first", "name": "Planning"},
        ),
        actor_id="macos:main",
    )

    assert receipt.state == "completed"
    assert hub.summaries() == [
        {"session_id": "first", "name": "Planning", "cursor": 4}
    ]
    assert any(event.type == "session.renamed" for event in session.events())
    history = next(
        panel for panel in session.snapshot().panels if panel.key == "sessions_history"
    )
    assert history.items[0]["name"] == "Planning"
    hub.close()


def test_session_compact_returns_canonical_receipt(tmp_path: Path) -> None:
    compacted: list[str] = []

    def factory(session_id: str, emit):  # type: ignore[no-untyped-def]
        def compact(_payload: dict[str, object]) -> dict[str, object]:
            compacted.append(session_id)
            _ = emit("session.compacted", {"session_id": session_id})
            return {"compacted": True}

        return {"session.compact": compact}

    hub = WorkspaceHub(root=tmp_path, handler_factory=factory)
    session, _ = hub.create("first")

    receipt = hub.compact(
        _command("session.compact", "compact-1", 0, {}),
        actor_id="macos:main",
    )

    assert receipt.state == "completed"
    assert receipt.result_event_cursor == 4
    assert compacted == ["first"]
    assert any(event.type == "session.compacted" for event in session.events())
    hub.close()
