from __future__ import annotations

import socket
import threading

import pytest

from birkin.native.bridge_commands import (
    NativeCommandCoordinator,
    NativeCommandExecution,
    NativeCommandExecutor,
)
from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.capability import CapabilityScope
from birkin.native.messages import NativeMessageFactory
from birkin.native.protocol import NativeEnvelope
from birkin.native.state import NativeConnectionState
from birkin.native.transport import NativeConnection, receive_frame
from birkin.workspace import CommandReceipt, WorkspaceCommand
from tests.native_bridge_support import envelope


class _UnusedAuthority:
    def submit(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt:
        raise AssertionError(f"unexpected execution: {command.type} by {actor_id}")


def _fixture() -> tuple[
    NativeCommandExecutor,
    NativeCommandExecution,
    socket.socket,
]:
    server_socket, client_socket = socket.socketpair()
    connection = NativeConnection(server_socket, peer_uid=None)
    state = NativeConnectionState.server()
    messages = NativeMessageFactory(
        instance_id="instance-1",
        server_version="1.0.0",
        session_id="session-1",
        command_types=frozenset({"chat.send", "chat.interrupt"}),
        session_presets=(),
    )
    return (
        NativeCommandExecutor(_UnusedAuthority(), messages),
        NativeCommandExecution(
            connection=connection,
            state=state,
            stream=NativeBridgeStream(
                connection,
                state,
                messages,
                heartbeat_interval=1,
                peer_timeout=1,
                capacity=8,
            ),
            scope=CapabilityScope(
                instance_id="instance-1",
                connection_id="connection-1",
                surface="macos",
                view_id="main",
            ),
        ),
        client_socket,
    )


def _command(
    command_type: str,
    command_id: str,
    *,
    surface: str = "macos",
) -> NativeEnvelope:
    return envelope(
        "command",
        frame_id=command_id,
        body={
            "command": {
                "protocol_version": 1,
                "command_id": command_id,
                "expected_cursor": 0,
                "type": command_type,
                "payload": {},
                "client_context": {"surface": surface, "view_id": "main"},
            },
        },
    )


def test_terminal_response_releases_lane_before_client_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, execution, peer = _fixture()
    coordinator = NativeCommandCoordinator(executor, cleanup=None)
    first = _command("chat.send", "outside-first", surface="web")
    retry = _command("chat.send", "outside-retry", surface="web")
    state_send = NativeConnectionState.send

    def allow_response(
        state: NativeConnectionState,
        response: NativeEnvelope,
    ) -> None:
        if state is not execution.state:
            state_send(state, response)

    def run_inline(thread: threading.Thread) -> None:
        thread.run()

    monkeypatch.setattr(NativeConnectionState, "send", allow_response)
    monkeypatch.setattr(threading.Thread, "start", run_inline)
    try:
        assert coordinator.submit(execution, first)
        first_response = receive_frame(peer)
        assert first_response.kind == "error"
        assert first_response.body["code"] == "E_CAPABILITY_SCOPE"

        assert coordinator.submit(execution, retry)
        retry_response = receive_frame(peer)
        assert retry_response.kind == "error"
        assert retry_response.body["code"] == "E_CAPABILITY_SCOPE"
    finally:
        execution.connection.close()
        peer.close()


def test_receipt_send_precedes_deferred_disconnect_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, execution, peer = _fixture()
    execution_started = threading.Event()
    release_execution = threading.Event()
    receipt_sent = threading.Event()
    cleanup_completed = threading.Event()
    ordering: list[str] = []
    state_send = NativeConnectionState.send

    def execute(
        _connection: NativeConnection,
        _state: NativeConnectionState,
        message: NativeEnvelope,
        _scope: CapabilityScope,
    ) -> NativeEnvelope:
        execution_started.set()
        assert release_execution.wait(timeout=2)
        return envelope(
            "receipt",
            frame_id="receipt-after-execution",
            in_reply_to=message.id,
            body={},
        )

    def allow_response(
        state: NativeConnectionState,
        response: NativeEnvelope,
    ) -> None:
        if state is not execution.state:
            state_send(state, response)

    def record_receipt(
        connection: NativeConnection,
        _response: NativeEnvelope,
    ) -> None:
        if connection is execution.connection:
            ordering.append("receipt")
            receipt_sent.set()

    def cleanup() -> None:
        ordering.append("cleanup")
        cleanup_completed.set()

    monkeypatch.setattr(executor, "execute", execute)
    monkeypatch.setattr(NativeConnectionState, "send", allow_response)
    monkeypatch.setattr(NativeConnection, "send", record_receipt)
    coordinator = NativeCommandCoordinator(executor, cleanup)
    try:
        assert coordinator.submit(
            execution,
            _command("chat.send", "deferred-disconnect"),
        )
        assert execution_started.wait(timeout=2)
        coordinator.disconnect()
        release_execution.set()

        assert receipt_sent.wait(timeout=2)
        assert cleanup_completed.wait(timeout=2)
        assert ordering == ["receipt", "cleanup"]
    finally:
        release_execution.set()
        execution.connection.close()
        peer.close()


def test_thread_start_failure_releases_control_lane_without_disturbing_normal_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, execution, peer = _fixture()
    normal_entered = threading.Event()
    release_normal = threading.Event()
    later_control_completed = threading.Event()
    cleanup_completed = threading.Event()
    executor_calls: list[str] = []
    cleanup_calls = 0

    def execute(
        _connection: NativeConnection,
        _state: NativeConnectionState,
        message: NativeEnvelope,
        _scope: CapabilityScope,
    ) -> None:
        command = WorkspaceCommand.parse(message.body.get("command"))
        executor_calls.append(command.command_id)
        if command.command_id == "active-normal":
            normal_entered.set()
            assert release_normal.wait(timeout=2)
        elif command.command_id == "later-control":
            later_control_completed.set()

    def cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        cleanup_completed.set()

    monkeypatch.setattr(executor, "execute", execute)
    coordinator = NativeCommandCoordinator(executor, cleanup)
    try:
        assert coordinator.submit(execution, _command("chat.send", "active-normal"))
        assert normal_entered.wait(timeout=1)
        original_start = threading.Thread.start

        def fail_start(_thread: threading.Thread) -> None:
            coordinator.disconnect()
            raise RuntimeError("injected thread-start failure")

        monkeypatch.setattr(threading.Thread, "start", fail_start)
        with pytest.raises(RuntimeError, match="injected thread-start failure"):
            _ = coordinator.submit(
                execution,
                _command("chat.interrupt", "failed-control"),
            )

        assert executor_calls == ["active-normal"]
        assert cleanup_calls == 0
        assert not coordinator.submit(execution, _command("chat.send", "other-normal"))

        monkeypatch.setattr(threading.Thread, "start", original_start)
        release_normal.set()
        assert cleanup_completed.wait(timeout=1)
        assert cleanup_calls == 1

        def run_inline(thread: threading.Thread) -> None:
            thread.run()

        monkeypatch.setattr(threading.Thread, "start", run_inline)
        assert coordinator.submit(
            execution,
            _command("chat.interrupt", "later-control"),
        )
        assert later_control_completed.is_set()
        assert cleanup_calls == 1
    finally:
        release_normal.set()
        execution.connection.close()
        peer.close()


def test_stream_suspend_failure_releases_normal_lane_without_disturbing_control_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, execution, peer = _fixture()
    control_entered = threading.Event()
    release_control = threading.Event()
    later_normal_completed = threading.Event()
    cleanup_completed = threading.Event()
    executor_calls: list[str] = []
    suspend_calls = 0
    resume_calls = 0
    cleanup_calls = 0

    def execute(
        _connection: NativeConnection,
        _state: NativeConnectionState,
        message: NativeEnvelope,
        _scope: CapabilityScope,
    ) -> None:
        command = WorkspaceCommand.parse(message.body.get("command"))
        executor_calls.append(command.command_id)
        if command.command_id == "active-control":
            control_entered.set()
            assert release_control.wait(timeout=2)
        elif command.command_id == "later-normal":
            later_normal_completed.set()

    def cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        cleanup_completed.set()

    monkeypatch.setattr(executor, "execute", execute)
    coordinator = NativeCommandCoordinator(executor, cleanup)
    try:
        assert coordinator.submit(
            execution,
            _command("chat.interrupt", "active-control"),
        )
        assert control_entered.wait(timeout=1)
        original_suspend = execution.stream.suspend
        original_resume = execution.stream.resume

        def fail_suspend() -> None:
            nonlocal suspend_calls
            suspend_calls += 1
            coordinator.disconnect()
            raise RuntimeError("injected stream-suspend failure")

        def count_resume() -> None:
            nonlocal resume_calls
            resume_calls += 1
            original_resume()

        def run_inline(thread: threading.Thread) -> None:
            thread.run()

        monkeypatch.setattr(execution.stream, "suspend", fail_suspend)
        monkeypatch.setattr(execution.stream, "resume", count_resume)
        monkeypatch.setattr(threading.Thread, "start", run_inline)
        with pytest.raises(RuntimeError, match="injected stream-suspend failure"):
            _ = coordinator.submit(execution, _command("chat.send", "failed-normal"))

        assert executor_calls == ["active-control"]
        assert (suspend_calls, resume_calls, cleanup_calls) == (1, 0, 0)
        assert not coordinator.submit(
            execution,
            _command("chat.interrupt", "other-control"),
        )

        release_control.set()
        assert cleanup_completed.wait(timeout=1)
        assert cleanup_calls == 1

        def count_suspend() -> None:
            nonlocal suspend_calls
            suspend_calls += 1
            original_suspend()

        monkeypatch.setattr(execution.stream, "suspend", count_suspend)
        assert coordinator.submit(execution, _command("chat.send", "later-normal"))
        assert later_normal_completed.is_set()
        assert (suspend_calls, resume_calls, cleanup_calls) == (2, 1, 1)
    finally:
        release_control.set()
        execution.connection.close()
        peer.close()
