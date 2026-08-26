from __future__ import annotations

import threading
from pathlib import Path

import pytest

from birkin.workspace.contracts import ClientContext, PROTOCOL_VERSION, WorkspaceCommand
from birkin.workspace.service import WorkspaceService
from birkin.workspace.terminal_output import TerminalOutputBatch, TerminalOutputPump
from birkin.workspace.terminal_policy import ApprovedTerminalLaunch, TerminalIdentity, TerminalInputIntent
from birkin.workspace.terminal_session import TerminalSessions
from tests.terminal_lock_test_support import install_attempt_lock
from tests.test_terminal_output_runtime import EventProcess, process_factory

_TIMEOUT = 2.0


def test_claim_drain_handoff_cannot_be_overtaken(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WorkspaceService(root=tmp_path / "journal", session_id="session-1", handlers={})
    process = EventProcess()
    drained = threading.Event()
    release = threading.Event()
    second_seen = threading.Event()
    attempting_emit = threading.Event()
    original = TerminalOutputPump.drain

    def blocked_drain(self: TerminalOutputPump, timeout: float) -> TerminalOutputBatch:
        batch = original(self, timeout)
        if batch.text == "FIRST":
            drained.set()
            assert release.wait(_TIMEOUT)
        return batch

    monkeypatch.setattr(TerminalOutputPump, "drain", blocked_drain)

    def emit(kind: str, payload: dict[str, object]) -> object:
        if kind not in {"terminal.opened", "terminal.output"}:
            return payload
        event = service.emit(kind, payload)
        if kind == "terminal.output" and payload.get("data") == "SECOND":
            second_seen.set()
        return event

    sessions = TerminalSessions("session-1", emit, process_factory(process))
    launch = ApprovedTerminalLaunch(Path("cmd.exe"), tmp_path, {}, "approval")
    service.set_handlers({"terminal.create": lambda _payload: sessions.create(launch)})
    receipt = service.submit(
        WorkspaceCommand(
            PROTOCOL_VERSION,
            "create",
            0,
            "terminal.create",
            {"actor_kind": "native_human", "cwd": str(tmp_path)},
            ClientContext("windows", "terminal"),
        ),
        actor_id="windows:terminal",
    )
    opened = receipt.transient_result
    assert isinstance(opened, dict)
    identity = TerminalIdentity(str(opened["terminal_id"]), str(opened["lease"]))
    install_attempt_lock(sessions, identity.terminal_id, attempting_emit)
    done = threading.Event()

    def submit() -> None:
        _ = sessions.input(TerminalInputIntent(identity, 1, b"input"))
        done.set()

    producer = threading.Thread(target=submit)
    producer.start()
    try:
        assert process.write_ready.wait(_TIMEOUT)
        process.publish(b"FIRST")
        assert drained.wait(_TIMEOUT)
        process.publish(b"SECOND")
        assert attempting_emit.wait(_TIMEOUT)
        assert not second_seen.is_set()
        release.set()
        producer.join(_TIMEOUT)
        assert done.is_set()
        assert second_seen.wait(_TIMEOUT)
        output = [event for event in service.events() if event.type == "terminal.output"]
        assert [event.payload["data"] for event in output] == ["FIRST", "SECOND"]
        assert [event.payload["sequence"] for event in output] == [1, 2]
        snapshot = service.snapshot().to_json()
        assert str(snapshot).index("FIRST") < str(snapshot).index("SECOND")
    finally:
        release.set()
        sessions.close_all()
