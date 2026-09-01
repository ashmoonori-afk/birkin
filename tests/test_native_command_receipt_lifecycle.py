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
from birkin.native.transport import NativeConnection
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


def _receipt_fixture() -> tuple[
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
        command_types=frozenset({"chat.send"}),
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


def _receipt_command() -> NativeEnvelope:
    return envelope(
        "command",
        frame_id="deferred-disconnect",
        body={
            "command": {
                "protocol_version": 1,
                "command_id": "deferred-disconnect",
                "expected_cursor": 0,
                "type": "chat.send",
                "payload": {},
                "client_context": {"surface": "macos", "view_id": "main"},
            },
        },
    )


def test_receipt_send_precedes_deferred_disconnect_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, execution, peer = _receipt_fixture()
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
        assert coordinator.submit(execution, _receipt_command())
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
