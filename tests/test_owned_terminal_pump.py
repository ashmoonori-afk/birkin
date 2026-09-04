from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast, final

import pytest

from birkin.workspace.contracts import (
    ClientContext,
    ProtocolError,
    TerminalSequenceRejected,
    TerminalSignalRejected,
    WorkspaceCommand,
)
from birkin.workspace.darwin_terminal_process import DarwinTerminalProcess
from birkin.workspace.owned_terminal_commands import TerminalCommands
from birkin.workspace.owned_terminal_pty import (
    MAX_OUTPUT_BYTES,
    MAX_SCREEN_BYTES,
    PtySupport,
    TerminalSession,
)
from birkin.workspace.owned_terminal_session import TerminalSessionOwner
from birkin.workspace.records import WorkspaceEvent
from birkin.workspace.service import WorkspaceService


@final
class FakeProcess:
    def __init__(self, events: list[str] | None = None) -> None:
        self.pid: int = 99123
        self.status: int | None = None
        self.events: list[str] | None = events

    def poll(self) -> int | None:
        return self.status


@final
class Recorder:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.order: list[str] | None = events

    def __call__(self, kind: str, payload: dict[str, object]) -> object:
        self.events.append((kind, payload))
        if self.order is not None:
            self.order.append(kind)
        return payload


def session(
    tmp_path: Path,
    *,
    process: FakeProcess | None = None,
    master_fd: int = -1,
) -> TerminalSession:
    return TerminalSession(
        terminal_id="terminal-test",
        process=cast(
            DarwinTerminalProcess,
            cast(object, process or FakeProcess()),
        ),
        master_fd=master_fd,
        pty=PtySupport(
            open_pty=lambda: (-1, -1),
            set_nonblocking=lambda _fd: None,
            set_window_size=lambda _fd, _columns, _rows: None,
        ),
        cwd=tmp_path,
        lease="lease-secret",
        lease_expires_at=100.0,
        monotonic=lambda: 0.0,
    )


@pytest.mark.parametrize("split", range(1, 11))
def test_incremental_utf8_decoder_preserves_every_byte_split(
    tmp_path: Path, split: int
) -> None:
    terminal = session(tmp_path)
    encoded = "한€😀".encode()

    first = cast(str, terminal.record_output(encoded[:split])["data"])
    second = cast(
        str, terminal.record_output(encoded[split:], final=True)["data"]
    )

    assert first + second == "한€😀"
    assert "\ufffd" not in first + second


def test_incremental_utf8_decoder_replaces_invalid_and_incomplete_final_bytes(
    tmp_path: Path,
) -> None:
    invalid = session(tmp_path)
    incomplete = session(tmp_path)

    assert invalid.record_output(b"A\xffB", final=True)["data"] == "A\ufffdB"
    assert incomplete.record_output(b"\xf0\x9f", final=False)["data"] == ""
    assert incomplete.record_output(b"", final=True)["data"] == "\ufffd"


def test_output_events_and_screen_remain_ordered_and_bounded(
    tmp_path: Path
) -> None:
    terminal = session(tmp_path)

    first = terminal.record_output(b"a" * MAX_OUTPUT_BYTES)
    second = terminal.record_output("😀".encode(), final=True)

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert len(cast(str, first["data"]).encode()) <= MAX_OUTPUT_BYTES
    assert len(terminal.screen.encode()) <= MAX_SCREEN_BYTES
    assert terminal.screen.endswith("😀")
    assert "\ufffd" not in terminal.screen


def test_output_pump_waits_through_quiet_readiness_before_delayed_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal = session(tmp_path, master_fd=42)
    readiness: Iterator[tuple[list[int], list[int], list[int]]] = iter([
        ([42], list[int](), list[int]()),
        (list[int](), list[int](), list[int]()),
        ([42], list[int](), list[int]()),
        (list[int](), list[int](), list[int]()),
    ])
    reads = iter([b"first-", b"delayed"])
    now = iter([0.0, 0.1, 0.2, 0.3, 1.0])

    def next_readiness(
        *_args: object,
    ) -> tuple[list[int], list[int], list[int]]:
        return next(readiness)

    def next_read(_fd: int, _size: int) -> bytes:
        return next(reads)

    def next_now() -> float:
        return next(now)

    monkeypatch.setattr(
        "birkin.workspace.owned_terminal_pty.select.select",
        next_readiness,
    )
    monkeypatch.setattr(
        "birkin.workspace.owned_terminal_pty.os.read",
        next_read,
    )
    monkeypatch.setattr(
        "birkin.workspace.owned_terminal_pty.time.monotonic",
        next_now,
    )

    output, reached_eof = terminal.pump_output(timeout=1.0)

    assert output == b"first-delayed"
    assert reached_eof is False


def _commands(
    tmp_path: Path,
    recorder: Recorder,
    *,
    process: FakeProcess | None = None,
    master_fd: int = -1,
) -> tuple[TerminalCommands, TerminalSession]:
    owner = TerminalSessionOwner(recorder, lambda: 0.0)
    terminal = session(tmp_path, process=process, master_fd=master_fd)
    owner.register(terminal)
    return TerminalCommands(owner), terminal


def test_input_backend_failure_terminates_and_releases_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    process = FakeProcess(order)
    commands, terminal = _commands(
        tmp_path, Recorder(order), process=process, master_fd=42
    )

    def failed_write(_fd: int, _data: object) -> int:
        raise OSError("backend write failed")

    def terminate() -> None:
        order.append("terminate")
        process.status = -9

    def record_release(_fd: int) -> None:
        order.append("release")

    def terminate_process(_self: TerminalSession) -> None:
        terminate()

    def no_output(
        _self: TerminalSession,
        *,
        timeout: float,
        consume: Callable[[bytes, bool], None] | None = None,
    ) -> tuple[bytes, bool]:
        _ = timeout
        _ = consume
        return b"", False

    monkeypatch.setattr("birkin.workspace.owned_terminal_pty.os.write", failed_write)
    monkeypatch.setattr(
        "birkin.workspace.owned_terminal_pty.os.close",
        record_release,
    )
    monkeypatch.setattr(TerminalSession, "terminate_process", terminate_process)
    monkeypatch.setattr(TerminalSession, "pump_output", no_output)

    with pytest.raises(OSError, match="backend write failed"):
        _ = commands.input({
            "terminal_id": terminal.terminal_id,
            "lease": terminal.lease,
            "sequence": 1,
            "data": "top-secret",
        })

    assert order == ["terminate", "terminal.exited", "release"]
    assert terminal.lease is None
    assert terminal.input_sequence == 0
    assert "top-secret" not in str(order)


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_signal_backend_failure_terminates_and_releases_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    process = FakeProcess(order)
    commands, terminal = _commands(
        tmp_path, Recorder(order), process=process, master_fd=42
    )

    def terminate() -> None:
        order.append("terminate")
        process.status = -9

    def fail_signal(_pid: int, _signal: int) -> None:
        raise OSError("signal failed")

    def record_release(_fd: int) -> None:
        order.append("release")

    def terminate_process(_self: TerminalSession) -> None:
        terminate()

    def no_output(
        _self: TerminalSession,
        *,
        timeout: float,
        consume: Callable[[bytes, bool], None] | None = None,
    ) -> tuple[bytes, bool]:
        _ = timeout
        _ = consume
        return b"", False

    monkeypatch.setattr(
        "birkin.workspace.owned_terminal_commands.os.killpg",
        fail_signal,
    )
    monkeypatch.setattr(
        "birkin.workspace.owned_terminal_pty.os.close",
        record_release,
    )
    monkeypatch.setattr(TerminalSession, "terminate_process", terminate_process)
    monkeypatch.setattr(TerminalSession, "pump_output", no_output)

    with pytest.raises(OSError, match="signal failed"):
        _ = commands.signal({
            "terminal_id": terminal.terminal_id,
            "lease": terminal.lease,
            "signal": "TERM",
        })

    assert order == ["terminate", "terminal.exited", "release"]
    assert terminal.lease is None


def test_backend_failure_orders_output_exit_release_before_command_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    process = FakeProcess(order)
    service = WorkspaceService(
        root=tmp_path / "journal",
        session_id="session-test",
        handlers={},
    )
    owner = TerminalSessionOwner(service.emit, lambda: 0.0)
    terminal = session(tmp_path, process=process, master_fd=42)
    owner.register(terminal)
    commands = TerminalCommands(owner)
    pump_calls = 0

    def pump(
        _self: TerminalSession,
        *,
        timeout: float,
        consume: Callable[[bytes, bool], None] | None = None,
    ) -> tuple[bytes, bool]:
        nonlocal pump_calls
        _ = timeout
        pump_calls += 1
        if pump_calls == 1 and consume is not None:
            consume(b"visible-output", False)
            return b"visible-output", False
        return b"", False

    def handler(payload: dict[str, object]) -> dict[str, object]:
        _ = owner.capture_output(terminal, timeout=0.0)
        return commands.input(payload)

    service.set_handlers({"terminal.input": handler})

    def record_event(event: WorkspaceEvent) -> None:
        order.append(event.type)

    service.set_event_listener(record_event)

    def terminate() -> None:
        order.append("terminate")
        process.status = -9

    def terminate_process(_self: TerminalSession) -> None:
        terminate()

    def fail_write(_fd: int, _data: object) -> int:
        raise OSError("write failed")

    def record_release(_fd: int) -> None:
        order.append("release")

    monkeypatch.setattr(TerminalSession, "pump_output", pump)
    monkeypatch.setattr(TerminalSession, "terminate_process", terminate_process)
    monkeypatch.setattr(
        "birkin.workspace.owned_terminal_pty.os.write",
        fail_write,
    )
    monkeypatch.setattr(
        "birkin.workspace.owned_terminal_pty.os.close",
        record_release,
    )
    command = WorkspaceCommand(
        protocol_version=1,
        command_id="failing-input",
        expected_cursor=0,
        type="terminal.input",
        payload={
            "terminal_id": terminal.terminal_id,
            "lease": terminal.lease,
            "sequence": 1,
            "data": "top-secret",
        },
        client_context=ClientContext(surface="terminal", view_id="test"),
    )

    with pytest.raises(OSError, match="write failed"):
        _ = service.submit(command, actor_id="native:test")

    relevant = [
        item
        for item in order
        if item in {"terminal.output", "terminal.exited", "release", "command.failed"}
    ]
    assert relevant == [
        "terminal.output",
        "terminal.exited",
        "release",
        "command.failed",
    ]
    assert "top-secret" not in str(service.events())


def test_validation_and_sequence_refusals_leave_valid_terminal_alive(
    tmp_path: Path,
) -> None:
    process = FakeProcess()
    commands, terminal = _commands(tmp_path, Recorder(), process=process)

    with pytest.raises(TerminalSequenceRejected):
        _ = commands.input({
            "terminal_id": terminal.terminal_id,
            "lease": terminal.lease,
            "sequence": 2,
            "data": "not-written",
        })
    with pytest.raises(ProtocolError):
        _ = commands.input({
            "terminal_id": terminal.terminal_id,
            "lease": terminal.lease,
            "sequence": 1,
            "data": "",
        })
    with pytest.raises(TerminalSignalRejected):
        _ = commands.signal({
            "terminal_id": terminal.terminal_id,
            "lease": terminal.lease,
            "signal": "SEGV",
        })

    assert process.poll() is None
    assert terminal.lease == "lease-secret"
    assert terminal.input_sequence == 0
