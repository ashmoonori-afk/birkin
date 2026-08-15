"""Shared workspace session/event/command protocol contracts.

These tests intentionally exercise the durable protocol below terminal and web
presentation. A single session must serialize commands, replay ordered events,
deduplicate retries across threads/restarts, and derive actor provenance from
the authenticated service call rather than client JSON.
"""

from __future__ import annotations

import os
import stat
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

from birkin.workspace import journal as workspace_journal
from birkin.workspace import (
    CommandIdConflict,
    CommandReceipt,
    ProtocolError,
    StaleCursor,
    WorkspaceCommand,
    WorkspaceHub,
    WorkspaceService,
)
from birkin.workspace.journal import WorkspaceJournal


def _command(
    command_id: str,
    *,
    expected_cursor: int,
    text: str,
) -> WorkspaceCommand:
    return WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": command_id,
            "expected_cursor": expected_cursor,
            "type": "chat.send",
            "payload": {"text": text},
            "client_context": {"surface": "terminal", "view_id": "view-1"},
        }
    )


def test_restart_recovers_accepted_unfinished_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def handler(payload: dict[str, object]) -> dict[str, object]:
        calls.append(str(payload["text"]))
        return {"reply": "recovered"}

    command = _command("recover-after-crash", expected_cursor=0, text="once")
    first = WorkspaceService(
        root=tmp_path,
        session_id="recover",
        handlers={"chat.send": handler},
    )
    receipt, execute = first.accept(command, actor_id="terminal:one")
    assert execute is True
    assert receipt.state == "accepted"
    def owner_is_dead(_pid: int) -> bool:
        return False

    monkeypatch.setattr(workspace_journal, "_pid_alive", owner_is_dead)

    restarted = WorkspaceService(
        root=tmp_path,
        session_id="recover",
        handlers={"chat.send": handler},
    )
    recovered, execute = restarted.accept(
        command,
        actor_id="terminal:one",
    )
    assert execute is True
    completed = restarted.execute(command, recovered)
    assert completed.state == "completed"
    assert calls == ["once"]


def test_restart_recovers_orphaned_acceptance_event(
    tmp_path: Path,
) -> None:
    command = _command("orphaned-acceptance", expected_cursor=0, text="once")
    journal = WorkspaceJournal(tmp_path, "orphan")
    _ = journal.append(
        "command.accepted",
        actor_id="terminal:one",
        command_id=command.command_id,
        payload={
            "command_type": command.type,
            "fingerprint": command.fingerprint(),
        },
    )

    restarted = WorkspaceJournal(tmp_path, "orphan")
    receipt, execute = restarted.accept(
        command,
        actor_id="terminal:one",
    )
    assert execute is True
    assert receipt.duplicate is True
    assert receipt.accepted_cursor == 1


def test_restart_marks_started_unfinished_command_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _command("started-before-crash", expected_cursor=0, text="once")
    journal = WorkspaceJournal(tmp_path, "started")
    receipt, execute = journal.accept(
        command,
        actor_id="terminal:one",
    )
    assert execute is True
    _ = journal.append(
        "command.started",
        actor_id=receipt.actor_id,
        command_id=receipt.command_id,
        payload={"command_type": command.type},
    )
    def owner_is_dead(_pid: int) -> bool:
        return False

    monkeypatch.setattr(workspace_journal, "_pid_alive", owner_is_dead)

    restarted = WorkspaceJournal(tmp_path, "started")
    failed, execute = restarted.accept(
        command,
        actor_id="terminal:one",
    )
    assert execute is False
    assert failed.state == "failed"
    assert restarted.events()[-1].type == "command.failed"


def test_live_authority_does_not_recover_accepted_command(
    tmp_path: Path,
) -> None:
    command = _command("live-authority", expected_cursor=0, text="once")
    first = WorkspaceJournal(tmp_path, "shared")
    receipt, execute = first.accept(command, actor_id="terminal:one")
    assert execute is True
    assert receipt.state == "accepted"

    concurrent = WorkspaceJournal(tmp_path, "shared")
    duplicate, execute = concurrent.accept(
        command,
        actor_id="web:browser",
    )
    assert execute is False
    assert duplicate.duplicate is True
    assert duplicate.state == "accepted"


def test_session_identifier_cannot_escape_workspace_root(
    tmp_path: Path,
) -> None:
    for session_id in (".", ".."):
        with pytest.raises(ProtocolError, match="session_id"):
            _ = WorkspaceService(
                root=tmp_path / "workspace",
                session_id=session_id,
                handlers={},
            )
    assert not (tmp_path / "events.jsonl").exists()


def test_workspace_journal_paths_are_owner_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chmod_requests: list[tuple[Path, int]] = []
    open_requests: list[tuple[Path, int]] = []
    original_chmod = os.chmod
    original_open = os.open

    def tracked_chmod(path: str | os.PathLike[str], mode: int) -> None:
        chmod_requests.append((Path(path), mode))
        original_chmod(path, mode)

    def tracked_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
    ) -> int:
        open_requests.append((Path(path), mode))
        return original_open(path, flags, mode)

    monkeypatch.setattr(os, "chmod", tracked_chmod)
    monkeypatch.setattr(os, "open", tracked_open)
    service = WorkspaceService(
        root=tmp_path,
        session_id="private",
        handlers={"chat.send": lambda _payload: {"reply": "ok"}},
    )
    command = _command("private-command", expected_cursor=0, text="secret")
    receipt = service.submit(command, actor_id="terminal:private")
    assert receipt.state == "completed"

    session_root = tmp_path / "private"
    receipt_path = next((session_root / "receipts").glob("*.json"))
    paths = (
        (tmp_path, 0o700),
        (session_root, 0o700),
        (session_root / "receipts", 0o700),
        (session_root / "events.jsonl", 0o600),
        (receipt_path, 0o600),
    )
    assert (tmp_path, 0o700) in chmod_requests
    assert (session_root, 0o700) in chmod_requests
    assert (session_root / "receipts", 0o700) in chmod_requests
    assert (session_root / "events.jsonl", 0o600) in chmod_requests
    assert (session_root / "events.jsonl", 0o600) in open_requests
    assert any(
        path.parent == session_root / "receipts"
        and path.name.endswith(".tmp")
        and mode == 0o600
        for path, mode in open_requests
    )

    if os.name == "posix":
        for path, expected_mode in paths:
            assert stat.S_IMODE(path.stat().st_mode) == expected_mode


def test_on_accepted_side_effect_runs_once_for_duplicate_interrupt(
    tmp_path: Path,
) -> None:
    hub = WorkspaceHub(
        root=tmp_path,
        handlers={"chat.interrupt": lambda _payload: {"interrupted": True}},
    )
    session, _ = hub.create("interrupt")
    command = WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": "interrupt-once",
            "expected_cursor": 0,
            "type": "chat.interrupt",
            "payload": {},
            "client_context": {
                "surface": "web",
                "view_id": "browser",
            },
        }
    )
    signals: list[str] = []
    first = session.submit(
        command,
        actor_id="web:browser",
        on_accepted=lambda: signals.append("interrupt"),
    )
    duplicate = session.submit(
        command,
        actor_id="web:browser",
        on_accepted=lambda: signals.append("duplicate"),
    )
    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert signals == ["interrupt"]
    hub.close()


def test_interrupt_acceptance_can_signal_while_turn_is_running(
    tmp_path: Path,
) -> None:
    turn_started = threading.Event()
    release_turn = threading.Event()

    def chat(_payload: dict[str, object]) -> dict[str, object]:
        turn_started.set()
        assert release_turn.wait(timeout=2)
        return {"reply": "released"}

    hub = WorkspaceHub(
        root=tmp_path,
        handlers={
            "chat.send": chat,
            "chat.interrupt": lambda _payload: {"interrupted": True},
        },
    )
    session, _ = hub.create("live-interrupt")
    send = _command("long-turn", expected_cursor=0, text="wait")
    _ = session.submit(send, actor_id="web:browser")
    assert turn_started.wait(timeout=2)
    interrupt = WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": "interrupt-live-turn",
            "expected_cursor": session.snapshot().cursor,
            "type": "chat.interrupt",
            "payload": {},
            "client_context": {
                "surface": "web",
                "view_id": "browser",
            },
        }
    )
    accepted = session.submit(
        interrupt,
        actor_id="web:browser",
        on_accepted=release_turn.set,
    )
    assert accepted.state == "accepted"
    assert release_turn.is_set()
    hub.close()


def test_session_close_wakes_stream_waiter(tmp_path: Path) -> None:
    hub = WorkspaceHub(
        root=tmp_path,
        handlers={"chat.send": lambda _payload: {"reply": "ok"}},
    )
    session, _ = hub.create("stream-close")
    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(
            session.wait_events,
            after=0,
            until=None,
            timeout=30,
        )
        hub.close()
        assert waiting.result(timeout=2) == ()
    assert session.closed is True


def test_session_close_cancels_commands_queued_behind_active(
    tmp_path: Path,
) -> None:
    active = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    calls: list[str] = []

    def handler(payload: dict[str, object]) -> dict[str, object]:
        calls.append(str(payload["text"]))
        if payload["text"] == "first":
            active.set()
            assert release.wait(2)
        return {"ok": True}

    hub = WorkspaceHub(root=tmp_path, handlers={"chat.send": handler})
    session, _ = hub.create("close-queue")
    first = _command("close-first", expected_cursor=0, text="first")
    _ = session.submit(first, actor_id="terminal:one")
    assert active.wait(2)
    second = _command(
        "close-second",
        expected_cursor=session.snapshot().cursor,
        text="second",
    )
    _ = session.submit(second, actor_id="terminal:one")
    original_cancel = session.service.cancel

    def cancel(
        receipt: CommandReceipt,
        *,
        reason: str,
    ) -> CommandReceipt:
        result = original_cancel(receipt, reason=reason)
        cancelled.set()
        return result

    session.service.cancel = cancel
    with ThreadPoolExecutor(max_workers=1) as executor:
        closing = executor.submit(session.close)
        assert cancelled.wait(2)
        release.set()
        _ = closing.result(timeout=2)
    assert calls == ["first"]
    failed = [
        event
        for event in session.events()
        if event.command_id == second.command_id
    ]
    assert failed[-1].type == "command.failed"


def _service(
    root: Path,
    handler: Callable[[dict[str, object]], dict[str, object]],
) -> WorkspaceService:
    return WorkspaceService(
        root=root,
        session_id="session-1",
        handlers={"chat.send": handler},
    )


def test_duplicate_command_executes_once_across_concurrent_clients(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    calls_lock = threading.Lock()
    start = threading.Barrier(3)

    def handle(payload: dict[str, object]) -> dict[str, object]:
        with calls_lock:
            calls.append(str(payload["text"]))
        return {"reply": "done"}

    service = _service(tmp_path, handle)
    command = _command(
        "terminal-1:command-1",
        expected_cursor=0,
        text="run once",
    )

    def submit(actor_id: str) -> CommandReceipt:
        _ = start.wait(timeout=2)
        return service.submit(command, actor_id=actor_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit, "terminal:one")
        second = pool.submit(submit, "web:two")
        _ = start.wait(timeout=2)
        receipts = [first.result(timeout=2), second.result(timeout=2)]

    assert calls == ["run once"]
    assert {receipt.command_id for receipt in receipts} == {
        "terminal-1:command-1"
    }
    assert sorted(receipt.duplicate for receipt in receipts) == [False, True]
    assert len({receipt.accepted_cursor for receipt in receipts}) == 1


def test_duplicate_precedes_stale_check_and_conflicting_reuse_is_rejected(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path,
        lambda payload: {"reply": payload["text"]},
    )
    original = _command(
        "terminal-1:command-1",
        expected_cursor=0,
        text="first",
    )
    receipt = service.submit(original, actor_id="terminal:one")

    stale_duplicate = _command(
        "terminal-1:command-1",
        expected_cursor=0,
        text="first",
    )
    duplicate = service.submit(stale_duplicate, actor_id="web:two")
    assert duplicate.duplicate is True
    assert duplicate.accepted_cursor == receipt.accepted_cursor

    conflicting = _command(
        "terminal-1:command-1",
        expected_cursor=service.snapshot().cursor,
        text="different payload",
    )
    with pytest.raises(CommandIdConflict):
        _ = service.submit(conflicting, actor_id="web:two")


def test_stale_cursor_is_rejected_and_events_are_monotonic(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        lambda payload: {"reply": str(payload["text"]).upper()},
    )
    first = _command(
        "terminal-1:command-1",
        expected_cursor=0,
        text="one",
    )
    _ = service.submit(first, actor_id="terminal:one")

    stale = _command(
        "web-2:command-1",
        expected_cursor=0,
        text="two",
    )
    with pytest.raises(StaleCursor) as raised:
        _ = service.submit(stale, actor_id="web:two")
    assert raised.value.current_cursor == service.snapshot().cursor

    second = _command(
        "web-2:command-1",
        expected_cursor=service.snapshot().cursor,
        text="two",
    )
    _ = service.submit(second, actor_id="web:two")

    events = service.events(after=0)
    assert [event.cursor for event in events] == list(range(1, len(events) + 1))
    assert [event.command_id for event in events] == [
        "terminal-1:command-1",
        "terminal-1:command-1",
        "terminal-1:command-1",
        "web-2:command-1",
        "web-2:command-1",
        "web-2:command-1",
    ]
    assert [event.type for event in events] == [
        "command.accepted",
        "command.started",
        "command.completed",
        "command.accepted",
        "command.started",
        "command.completed",
    ]


def test_receipt_and_event_replay_survive_service_restart(tmp_path: Path) -> None:
    first_calls: list[str] = []
    service = _service(
        tmp_path,
        lambda payload: first_calls.append(str(payload["text"])) or {"ok": True},
    )
    command = _command(
        "terminal-1:command-1",
        expected_cursor=0,
        text="persist me",
    )
    original = service.submit(command, actor_id="terminal:one")
    assert first_calls == ["persist me"]

    restarted_calls: list[str] = []
    restarted = _service(
        tmp_path,
        lambda payload: restarted_calls.append(str(payload["text"])) or {"ok": True},
    )
    duplicate = restarted.submit(command, actor_id="web:two")

    assert duplicate.duplicate is True
    assert duplicate.accepted_cursor == original.accepted_cursor
    assert restarted_calls == []
    assert [event.cursor for event in restarted.events(after=0)] == [1, 2, 3]
    assert restarted.snapshot().cursor == 3


def test_actor_is_server_derived_and_client_actor_field_is_rejected(
    tmp_path: Path,
) -> None:
    raw = {
        "protocol_version": 1,
        "command_id": "web-2:command-1",
        "expected_cursor": 0,
        "type": "chat.send",
        "payload": {"text": "hello"},
        "client_context": {"surface": "web", "view_id": "view-2"},
        "actor_id": "forged:admin",
    }
    with pytest.raises(ProtocolError):
        _ = WorkspaceCommand.parse(raw)

    command = _command(
        "web-2:command-1",
        expected_cursor=0,
        text="hello",
    )
    service = _service(tmp_path, lambda payload: {"ok": True})
    receipt = service.submit(command, actor_id="web:capability-owner")

    assert receipt.actor_id == "web:capability-owner"
    assert {
        event.actor_id for event in service.events(after=0)
    } == {"web:capability-owner"}


def test_snapshot_reduces_durable_conversation_and_panels(
    tmp_path: Path,
) -> None:
    service: WorkspaceService

    def handle(payload: dict[str, object]) -> dict[str, object]:
        text = str(payload["text"])
        _ = service.emit("message.user", {"text": text})
        _ = service.emit(
            "task.updated",
            {"task_id": "task-1", "summary": "Inspect workspace"},
        )
        _ = service.emit(
            "approval.requested",
            {"approval_id": "approval-1", "summary": "Run safe action"},
        )
        for event_type, summary in (
            ("file.updated", "Changed file"),
            ("session.updated", "Earlier session"),
            ("activity.recorded", "Activity"),
            ("cron.updated", "Nightly schedule"),
            ("memory.updated", "Remembered preference"),
            ("checkpoint.created", "Checkpoint"),
            ("status.updated", "Runtime status"),
        ):
            _ = service.emit(event_type, {"summary": summary})
        _ = service.emit(
            "message.assistant.completed",
            {"text": "durable reply"},
        )
        return {"reply": "durable reply"}

    service = _service(tmp_path, handle)
    command = _command(
        "terminal-1:durable-snapshot",
        expected_cursor=0,
        text="persist conversation",
    )
    _ = service.submit(command, actor_id="terminal:one")

    snapshot = service.snapshot().to_json()
    conversation = cast(list[dict[str, object]], snapshot["conversation"])
    assert [
        message["text"] for message in conversation
    ] == ["persist conversation", "durable reply"]
    panel_list = cast(list[dict[str, object]], snapshot["panels"])
    panels = {
        str(panel["key"]): cast(list[dict[str, object]], panel["items"])
        for panel in panel_list
    }
    assert panels["tasks_runs"][0]["summary"] == "Inspect workspace"
    assert panels["approvals"][0]["summary"] == "Run safe action"
    for key in (
        "files_evidence",
        "sessions_history",
        "activity_logs",
        "cron",
        "memory_skills",
        "checkpoints_restore",
        "settings_status",
    ):
        assert panels[key], key

    restarted = WorkspaceService(
        root=tmp_path,
        session_id="session-1",
        handlers={},
    )
    assert restarted.snapshot().to_json() == snapshot
