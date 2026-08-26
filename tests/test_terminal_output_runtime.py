from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import final

import pytest

from birkin.workspace.contracts import ClientContext, PROTOCOL_VERSION, ProtocolError, WorkspaceCommand
from birkin.workspace.records import WorkspaceEvent
from birkin.workspace.service import WorkspaceService
from birkin.workspace.terminal_policy import ApprovedTerminalLaunch, TerminalIdentity, TerminalInputIntent
from birkin.workspace.terminal_session import TerminalSessions
from tests.terminal_lock_test_support import install_attempt_lock

_TIMEOUT = 2.0


@final
class EventProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.writes: list[bytes] = []
        self._chunks: deque[bytes] = deque()
        self._status: int | None = None
        self._closed = False
        self._condition = threading.Condition()
        self.write_ready = threading.Event()

    def poll(self) -> int | None:
        with self._condition:
            return self._status

    def read(self, max_bytes: int, timeout: float | None) -> bytes:
        with self._condition:
            def ready() -> bool:
                return bool(self._chunks) or self._status is not None or self._closed

            if not ready() and not self._condition.wait_for(ready, timeout):
                return b""
            if not self._chunks:
                return b""
            chunk = self._chunks.popleft()
            if len(chunk) > max_bytes:
                self._chunks.appendleft(chunk[max_bytes:])
            return chunk[:max_bytes]

    def write(self, data: bytes, timeout: float) -> None:
        del timeout
        self.writes.append(data)
        self.write_ready.set()

    def resize(self, columns: int, rows: int) -> None:
        del columns, rows

    def signal(self, name: str) -> None:
        del name

    def close(self, exit_code: int = 1) -> None:
        with self._condition:
            self._closed = True
            if self._status is None:
                self._status = exit_code
            self._condition.notify_all()

    def publish(self, data: bytes) -> None:
        with self._condition:
            self._chunks.append(data)
            self._condition.notify_all()

    def exit(self, status: int) -> None:
        with self._condition:
            self._status = status
            self._condition.notify_all()


def process_factory(
    process: EventProcess,
) -> Callable[[Path, Path, Mapping[str, str], int, int], EventProcess]:
    def create(
        _shell: Path,
        _cwd: Path,
        _environment: Mapping[str, str],
        _columns: int,
        _rows: int,
    ) -> EventProcess:
        return process

    return create


def test_delayed_output_and_natural_exit_publish_without_followup_command_or_snapshot(
    tmp_path: Path,
) -> None:
    # Given runtime listeners subscribed before a terminal is created
    process = EventProcess()
    output_ready, exit_ready = threading.Event(), threading.Event()
    events: list[tuple[str, dict[str, object]]] = []

    def emit(kind: str, payload: dict[str, object]) -> object:
        events.append((kind, payload))
        if kind == "terminal.output" and payload.get("data") == "DELAYED_MARKER":
            output_ready.set()
        if kind == "terminal.exited":
            exit_ready.set()
        return payload

    sessions = TerminalSessions(
        "session-1", emit, process_factory(process), lease_ttl=60.0
    )
    opened = sessions.create(ApprovedTerminalLaunch(Path("cmd.exe"), tmp_path, {}, "approval"))
    try:
        # When delayed bytes and natural exit occur after create returned
        process.publish(b"DELAYED_MARKER")
        assert output_ready.wait(_TIMEOUT)
        process.exit(7)
        # Then output and exactly one exit publish without another command/snapshot
        assert exit_ready.wait(_TIMEOUT)
        assert [kind for kind, _ in events].count("terminal.exited") == 1
        assert any(payload.get("terminal_id") == opened["terminal_id"] for kind, payload in events if kind == "terminal.output")
    finally:
        sessions.close_all()


def test_sensitive_assignment_is_registered_before_write_and_masked_from_history(
    tmp_path: Path,
) -> None:
    # Given a terminal session and a sensitive literal parsed at the boundary
    process = EventProcess()
    output_ready = threading.Event()
    outputs: list[str] = []

    def emit(kind: str, payload: dict[str, object]) -> object:
        if kind == "terminal.output":
            outputs.append(str(payload["data"]))
            output_ready.set()
        return payload

    sessions = TerminalSessions("session-1", emit, process_factory(process))
    opened = sessions.create(ApprovedTerminalLaunch(Path("cmd.exe"), tmp_path, {}, "approval"))
    identity = TerminalIdentity(str(opened["terminal_id"]), str(opened["lease"]))
    intent = TerminalInputIntent(identity, 1, b"set PASSWORD=value123\r\n")
    try:
        # When input is written and its echo arrives in split chunks
        _ = sessions.input(intent)
        process.publish(b"set PASSWORD=val")
        process.publish(b"ue123\r\nvalue123 later")
        assert output_ready.wait(_TIMEOUT)
        # Then the literal is absent from live events and canonical history
        snapshot = sessions.snapshot(TerminalIdentity(identity.terminal_id, None))
        combined = "".join(outputs) + str(snapshot["screen"])
        assert "value123" not in combined
        assert combined.count("[REDACTED]") >= 2
        assert process.writes == [intent.data]
    finally:
        sessions.close_all()


def test_command_and_delayed_output_emit_in_sequence_order(
    tmp_path: Path,
) -> None:
    # Given command-drained output blocked inside its journal callback
    service = WorkspaceService(root=tmp_path / "journal", session_id="session-1", handlers={})
    process = EventProcess()
    first_callback = threading.Event()
    release_first = threading.Event()
    second_callback = threading.Event()
    second_journaled = threading.Event()
    attempting_emit = threading.Event()
    live_sequences: list[int] = []

    def record_output(event: WorkspaceEvent) -> None:
        if event.type == "terminal.output":
            sequence = event.payload["sequence"]
            assert isinstance(sequence, int) and not isinstance(sequence, bool)
            live_sequences.append(sequence)
            if sequence == 2:
                second_journaled.set()

    _ = service.add_event_listener(record_output)

    def emit(kind: str, payload: dict[str, object]) -> object:
        if kind == "terminal.opened":
            return service.emit(kind, payload)
        if kind != "terminal.output":
            return payload
        if payload["data"] == "FIRST":
            first_callback.set()
            assert release_first.wait(_TIMEOUT)
        elif payload["data"] == "SECOND":
            second_callback.set()
        return service.emit(kind, payload)

    sessions = TerminalSessions("session-1", emit, process_factory(process))
    launch = ApprovedTerminalLaunch(Path("cmd.exe"), tmp_path, {}, "approval")

    def create_terminal(_payload: dict[str, object]) -> dict[str, object]:
        return sessions.create(launch)

    service.set_handlers({"terminal.create": create_terminal})
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
    command_done = threading.Event()

    def command_output() -> None:
        _ = sessions.input(TerminalInputIntent(identity, 1, b"input"))
        command_done.set()

    producer = threading.Thread(target=command_output)
    producer.start()
    try:
        try:
            assert process.write_ready.wait(_TIMEOUT)
            process.publish(b"FIRST")
            assert first_callback.wait(_TIMEOUT)
            # When delayed pump output arrives while the command callback is blocked
            process.publish(b"SECOND")
            # Then the later actor reaches the held lock but cannot publish
            assert attempting_emit.wait(_TIMEOUT)
            assert not second_callback.is_set()
        finally:
            release_first.set()
            producer.join(_TIMEOUT)
        assert command_done.is_set()
        assert second_callback.wait(_TIMEOUT)
        assert second_journaled.wait(_TIMEOUT)
        journal_sequences = [
            event.payload["sequence"]
            for event in service.events()
            if event.type == "terminal.output"
        ]
        reconnect = service.snapshot().to_json()
        assert journal_sequences == [1, 2]
        assert live_sequences == [1, 2]
        assert str(reconnect).index("FIRST") < str(reconnect).index("SECOND")
    finally:
        sessions.close_all()


def test_workspace_service_allows_only_validated_terminal_runtime_events(tmp_path: Path) -> None:
    # Given a service with a subscriber before a background runtime event
    service = WorkspaceService(root=tmp_path, session_id="session-1", handlers={})
    observed: list[WorkspaceEvent] = []
    _ = service.add_event_listener(observed.append)
    # When delayed output and exit are emitted outside a command
    output = service.emit("terminal.output", {"terminal_id": "terminal-1", "sequence": 1, "data": "safe"})
    exited = service.emit("terminal.exited", {"terminal_id": "terminal-1", "exit_status": 0, "reason": "exited"})
    # Then stable runtime identities are journaled and every other type stays closed
    assert output.actor_id == exited.actor_id == "runtime:terminal"
    assert output.command_id == "terminal-1-output-1"
    assert exited.command_id == "terminal-1-exit"
    assert len(observed) == 2
    with pytest.raises(ProtocolError, match="outside a command"):
        _ = service.emit("terminal.resized", {"terminal_id": "terminal-1"})
    with pytest.raises(ProtocolError, match="sequence"):
        _ = service.emit("terminal.output", {"terminal_id": "terminal-1", "sequence": 0, "data": "bad"})
