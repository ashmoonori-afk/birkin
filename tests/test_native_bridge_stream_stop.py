from __future__ import annotations

import socket
import threading

import pytest

from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.messages import NativeMessageFactory
from birkin.native.protocol import NativeEnvelope
from birkin.native.state import NativeConnectionState
from birkin.native.transport import NativeConnection
from birkin.workspace.records import WorkspaceEvent


def _writer_fixture() -> tuple[
    NativeBridgeStream,
    NativeConnection,
    socket.socket,
]:
    server_socket, peer = socket.socketpair()
    connection = NativeConnection(server_socket, peer_uid=None)
    state = NativeConnectionState.server()
    messages = NativeMessageFactory(
        instance_id="instance-1",
        server_version="1.0.0",
        session_id="session-1",
        command_types=frozenset(),
        session_presets=(),
    )
    stream = NativeBridgeStream(
        connection,
        state,
        messages,
        heartbeat_interval=1,
        peer_timeout=1,
        capacity=8,
    )
    stream.activate(after_cursor=0)
    return stream, connection, peer


def _writer_event() -> WorkspaceEvent:
    return WorkspaceEvent(
        protocol_version=1,
        session_id="session-1",
        cursor=1,
        event_id="event-1",
        type="chat.message",
        timestamp="2026-09-01T00:00:00Z",
        actor_id="test",
        command_id="command-1",
        payload={"text": "trigger writer"},
    )


def _ignore_state_send(
    _state: NativeConnectionState,
    _message: NativeEnvelope,
) -> None:
    return None


def test_stop_interrupts_blocked_writer_and_proves_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream, connection, peer = _writer_fixture()
    send_entered = threading.Event()
    release_send = threading.Event()
    interrupted = threading.Event()

    def block_send(
        candidate: NativeConnection,
        _message: NativeEnvelope,
    ) -> None:
        if candidate is connection:
            send_entered.set()
            assert release_send.wait(timeout=10)

    def interrupt(candidate: NativeConnection) -> None:
        if candidate is connection:
            interrupted.set()
            release_send.set()

    monkeypatch.setattr(NativeConnectionState, "send", _ignore_state_send)
    monkeypatch.setattr(NativeConnection, "send", block_send)
    monkeypatch.setattr(NativeConnection, "interrupt", interrupt)
    stream.publish(_writer_event())
    stream.start()
    writer = next(
        candidate
        for candidate in threading.enumerate()
        if candidate.name == "birkin-native-writer"
    )
    try:
        assert send_entered.wait(timeout=2)

        stream.stop()

        assert interrupted.is_set()
        assert not writer.is_alive()
        assert stream.failure is None
    finally:
        release_send.set()
        writer.join(timeout=2)
        connection.close()
        peer.close()


def test_stop_records_failure_when_writer_survives_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream, connection, peer = _writer_fixture()
    send_entered = threading.Event()
    release_send = threading.Event()
    interrupted = threading.Event()

    def block_send(
        candidate: NativeConnection,
        _message: NativeEnvelope,
    ) -> None:
        if candidate is connection:
            send_entered.set()
            assert release_send.wait(timeout=10)

    def record_interrupt(candidate: NativeConnection) -> None:
        if candidate is connection:
            interrupted.set()

    monkeypatch.setattr(NativeConnectionState, "send", _ignore_state_send)
    monkeypatch.setattr(NativeConnection, "send", block_send)
    monkeypatch.setattr(NativeConnection, "interrupt", record_interrupt)
    stream.publish(_writer_event())
    stream.start()
    writer = next(
        candidate
        for candidate in threading.enumerate()
        if candidate.name == "birkin-native-writer"
    )
    try:
        assert send_entered.wait(timeout=2)

        stream.stop()

        failure = stream.failure
        assert isinstance(failure, TimeoutError)
        assert str(failure) == (
            "native writer did not terminate after connection interrupt"
        )
        assert interrupted.is_set()
        assert writer.is_alive()
    finally:
        release_send.set()
        writer.join(timeout=2)
        connection.close()
        peer.close()
