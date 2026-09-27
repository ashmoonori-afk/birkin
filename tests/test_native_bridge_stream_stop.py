from __future__ import annotations

import socket
import threading
import time

import pytest

from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.messages import NativeMessageFactory
from birkin.native.protocol import NativeEnvelope
from birkin.native.state import NativeConnectionState
from birkin.native.stream import NativeEventQueue
from birkin.native.transport import NativeConnection
from birkin.workspace.records import WorkspaceEvent


def _writer_fixture(
    *,
    heartbeat_interval: float = 1,
    peer_timeout: float = 1,
) -> tuple[
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
        heartbeat_interval=heartbeat_interval,
        peer_timeout=peer_timeout,
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


def test_stop_is_prompt_while_a_command_holds_the_send_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given production heartbeat timings and a running command that owns the
    send gate, When the connection stops, Then the writer leaves at once
    instead of outwaiting its gate wait and stop() records no failure."""
    stream, connection, peer = _writer_fixture(
        heartbeat_interval=30,
        peer_timeout=10,
    )
    interrupted = threading.Event()

    def record_interrupt(candidate: NativeConnection) -> None:
        if candidate is connection:
            interrupted.set()

    writer_woke = threading.Event()
    writers: list[threading.Thread] = []
    original_wait = NativeEventQueue.wait_for_pending

    def wait_then_signal(queue: NativeEventQueue, *, timeout: float) -> None:
        original_wait(queue, timeout=timeout)
        writers.append(threading.current_thread())
        writer_woke.set()

    monkeypatch.setattr(NativeConnectionState, "send", _ignore_state_send)
    monkeypatch.setattr(NativeConnection, "interrupt", record_interrupt)
    monkeypatch.setattr(NativeEventQueue, "wait_for_pending", wait_then_signal)
    stream.suspend()
    try:
        stream.publish(_writer_event())
        stream.start()
        # The pending event sends the writer on to the gate this thread holds.
        assert writer_woke.wait(timeout=2)

        started = time.monotonic()
        stream.stop()
        elapsed = time.monotonic() - started

        assert elapsed < 1.0
        assert stream.failure is None
        assert not writers[0].is_alive()
        assert not interrupted.is_set()
    finally:
        stream.resume()
        connection.close()
        peer.close()


def test_stop_is_prompt_when_a_heartbeat_follows_a_held_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given a command that owns the send gate and a peer that answered every
    heartbeat so far, When stop() lands while the writer waits for the gate,
    Then the heartbeat that follows cannot erase stop()'s wake-up and leave
    the writer waiting out the peer timeout."""
    stream, connection, peer = _writer_fixture(
        heartbeat_interval=0.05,
        peer_timeout=30,
    )
    answering = threading.Event()
    answering.set()
    pings: list[str] = []
    writers: list[threading.Thread] = []
    answered_three = threading.Event()

    def answer_ping(
        candidate: NativeConnection,
        message: NativeEnvelope,
    ) -> None:
        if candidate is connection and message.kind == "ping":
            writers.append(threading.current_thread())
            pings.append(message.id)
            if len(pings) >= 3:
                answered_three.set()
            if answering.is_set():
                stream.acknowledge_pong()

    monkeypatch.setattr(NativeConnectionState, "send", _ignore_state_send)
    monkeypatch.setattr(NativeConnection, "send", answer_ping)
    stream.suspend()
    try:
        stream.publish(_writer_event())
        stream.start()
        assert answered_three.wait(timeout=5)
        answering.clear()

        started = time.monotonic()
        stream.stop()
        elapsed = time.monotonic() - started

        assert elapsed < 1.0
        assert stream.failure is None
        assert not writers[0].is_alive()
    finally:
        stream.resume()
        connection.close()
        peer.close()


def test_stop_between_stop_check_and_heartbeat_is_not_erased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given an idle writer that already checked for stop and holds the gate,
    When stop() completes before the heartbeat clears the pong, Then the writer
    still leaves at once instead of waiting out the peer timeout."""
    stream, connection, peer = _writer_fixture(
        heartbeat_interval=0.05,
        peer_timeout=30,
    )
    queue_closed = threading.Event()
    stopper_started = threading.Event()
    stoppers: list[threading.Thread] = []
    writers: list[threading.Thread] = []
    original_close = NativeEventQueue.close
    original_drain = NativeEventQueue.drain

    def close_and_signal(queue: NativeEventQueue) -> None:
        original_close(queue)
        queue_closed.set()

    def drain_then_stop(
        queue: NativeEventQueue,
    ) -> tuple[dict[str, object], ...]:
        drained = original_drain(queue)
        if not stoppers:
            writers.append(threading.current_thread())
            stopper = threading.Thread(target=stream.stop, daemon=True)
            stoppers.append(stopper)
            stopper.start()
            stopper_started.set()
            assert queue_closed.wait(timeout=2)
        return drained

    def ignore_send(_candidate: NativeConnection, _message: NativeEnvelope) -> None:
        return None

    monkeypatch.setattr(NativeConnectionState, "send", _ignore_state_send)
    monkeypatch.setattr(NativeConnection, "send", ignore_send)
    monkeypatch.setattr(NativeEventQueue, "close", close_and_signal)
    monkeypatch.setattr(NativeEventQueue, "drain", drain_then_stop)
    stream.start()
    try:
        assert stopper_started.wait(timeout=2)

        stoppers[0].join(timeout=1.0)

        assert not stoppers[0].is_alive()
        assert stream.failure is None
        assert not writers[0].is_alive()
    finally:
        stream.stop()
        connection.close()
        peer.close()
