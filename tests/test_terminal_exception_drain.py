from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import final

import pytest

from birkin.workspace.command_failure import command_failure_receipt
from birkin.workspace.contracts import ClientContext, PROTOCOL_VERSION, WorkspaceCommand
from birkin.workspace.service import WorkspaceService
from birkin.workspace.terminal_policy import (
    ApprovedTerminalLaunch,
    TerminalIdentity,
    TerminalInputIntent,
    TerminalSignalIntent,
)
from birkin.workspace.terminal_session import TerminalSessions

_TIMEOUT = 2.0


@final
class ControlledFailureProcess:
    def __init__(self, operation: str, failure: OSError) -> None:
        self.pid = 4242
        self.operation = operation
        self.failure = failure
        self.failure_started = threading.Event()
        self.close_called = threading.Event()
        self._release = threading.Event()
        self._lock = threading.Lock()
        self._output_pending = True
        self._status: int | None = None

    def poll(self) -> int | None:
        with self._lock:
            return self._status

    def read(self, max_bytes: int, timeout: float | None) -> bytes:
        del timeout
        _ = self._release.wait()
        with self._lock:
            if self._output_pending:
                self._output_pending = False
                return f"{self.operation.upper()}_FIRST".encode()[:max_bytes]
            return b""

    def write(self, data: bytes, timeout: float) -> None:
        del data, timeout
        if self.operation == "write":
            self.failure_started.set()
            raise self.failure

    def resize(self, columns: int, rows: int) -> None:
        del columns, rows

    def signal(self, name: str) -> None:
        del name
        if self.operation == "signal":
            self.failure_started.set()
            raise self.failure

    def close(self, exit_code: int = 1) -> None:
        del exit_code
        self.close_called.set()

    def release_reader(self) -> None:
        with self._lock:
            self._status = 7
        self._release.set()


def _factory(process: ControlledFailureProcess) -> Callable[
    [Path, Path, Mapping[str, str], int, int], ControlledFailureProcess
]:
    return lambda _shell, _cwd, _environment, _columns, _rows: process


@pytest.mark.parametrize("operation", ["write", "signal"])
def test_backend_failure_teardown_precedes_command_failed(
    tmp_path: Path,
    operation: str,
) -> None:
    failure = OSError(f"injected-{operation}")
    process = ControlledFailureProcess(operation, failure)
    service = WorkspaceService(root=tmp_path / "journal", session_id="session-1", handlers={})
    live: list[str] = []

    def emit(kind: str, payload: dict[str, object]) -> object:
        live.append(kind)
        if kind in {"terminal.opened", "terminal.output", "terminal.exited"}:
            return service.emit(kind, payload)
        return payload

    sessions = TerminalSessions("session-1", emit, _factory(process))
    launch = ApprovedTerminalLaunch(Path("cmd.exe"), tmp_path, {}, "approval")
    identities: list[TerminalIdentity] = []

    def fail(_payload: dict[str, object]) -> dict[str, object]:
        identity = identities[0]
        if operation == "write":
            return sessions.input(TerminalInputIntent(identity, 1, b"input"))
        return sessions.signal(TerminalSignalIntent(identity, "INT"))

    service.set_handlers({
        "terminal.create": lambda _payload: sessions.create(launch),
        "terminal.fail": fail,
    })
    created = service.submit(
        WorkspaceCommand(
            PROTOCOL_VERSION, "create", 0, "terminal.create",
            {"actor_kind": "native_human", "cwd": str(tmp_path)},
            ClientContext("windows", "terminal"),
        ),
        actor_id="windows:terminal",
    )
    opened = created.transient_result
    assert isinstance(opened, dict)
    identity = TerminalIdentity(str(opened["terminal_id"]), str(opened["lease"]))
    identities.append(identity)
    start_cursor = service.snapshot().cursor
    errors: list[BaseException] = []

    def submit() -> None:
        try:
            _ = service.submit(
                WorkspaceCommand(
                    PROTOCOL_VERSION, f"fail-{operation}", start_cursor,
                    "terminal.fail", {}, ClientContext("windows", "terminal"),
                ),
                actor_id="windows:terminal",
            )
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=submit)
    worker.start()
    try:
        assert process.failure_started.wait(_TIMEOUT)
        assert process.close_called.wait(_TIMEOUT)
        assert not any(event.type == "command.failed" for event in service.events()[start_cursor:])
        process.release_reader()
        worker.join(_TIMEOUT)
        assert not worker.is_alive()
        assert errors == [failure]
        ordered = service.events()[start_cursor:]
        assert [event.type for event in ordered] == [
            "command.accepted", "command.started", "terminal.output",
            "terminal.exited", "command.failed",
        ]
        assert [kind for kind in live if kind != "terminal.opened"] == [
            "terminal.output", "terminal.exited",
        ]
        receipt = command_failure_receipt(failure)
        assert receipt is not None
        assert receipt.result_event_cursor == ordered[-1].cursor
        reconnect = str(service.snapshot().to_json())
        assert reconnect.index(f"{operation.upper()}_FIRST") < reconnect.index("exited")
    finally:
        process.release_reader()
        sessions.close_all()
