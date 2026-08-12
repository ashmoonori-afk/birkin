from __future__ import annotations

import os
import queue
import socket
import struct
import threading
from pathlib import Path

from birkin.voice.daemon_control import control_loop
from birkin.voice.daemon_state import (
    DaemonState,
    create_control_listener,
    request,
)
from birkin.voice.daemon_storage import claim_state


def _start_control_server(
    state_path: Path,
) -> tuple[
    socket.socket,
    DaemonState,
    threading.Event,
    threading.Event,
    threading.Thread,
]:
    listener = create_control_listener()
    state = DaemonState(
        instance_id="instance-id",
        token="control-token",
        pid=4242,
        host="127.0.0.1",
        port=listener.getsockname()[1],
    )
    claim_state(state_path, state)
    stop_requested = threading.Event()
    stopped = threading.Event()
    server = threading.Thread(
        target=control_loop,
        args=(
            listener,
            state_path,
            state,
            stop_requested,
            stopped,
        ),
    )
    server.start()
    return listener, state, stop_requested, stopped, server


def _stop_control_server(
    listener: socket.socket,
    stopped: threading.Event,
    server: threading.Thread,
) -> None:
    stopped.set()
    listener.close()
    server.join(timeout=2.0)
    assert server.is_alive() is False


def _abort_connection(connection: socket.socket) -> None:
    linger = struct.pack("hh" if os.name == "nt" else "ii", 1, 0)
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
    connection.close()


def test_control_loop_survives_failed_invalid_response(
    tmp_path: Path,
) -> None:
    listener, state, _stop_requested, stopped, server = (
        _start_control_server(tmp_path / "daemon.json")
    )
    invalid = socket.create_connection(
        (state.host, state.port),
        timeout=2.0,
    )
    invalid.sendall(b"not-json\n")
    _abort_connection(invalid)

    try:
        assert request(state, "STATUS") == "running"
    finally:
        _stop_control_server(listener, stopped, server)


def test_silent_control_peer_does_not_block_authenticated_status(
    tmp_path: Path,
) -> None:
    listener, state, _stop_requested, stopped, server = (
        _start_control_server(tmp_path / "daemon.json")
    )
    silent = socket.create_connection(
        (state.host, state.port),
        timeout=2.0,
    )

    try:
        assert request(state, "STATUS") == "running"
    finally:
        silent.close()
        _stop_control_server(listener, stopped, server)


def test_many_silent_control_peers_use_no_client_threads(
    tmp_path: Path,
) -> None:
    listener, state, _stop_requested, stopped, server = (
        _start_control_server(tmp_path / "daemon.json")
    )
    silent = [
        socket.create_connection(
            (state.host, state.port),
            timeout=2.0,
        )
        for _index in range(64)
    ]

    try:
        assert request(state, "STATUS") == "running"
        assert not any(
            thread.name == "birkin-voice-control-client"
            for thread in threading.enumerate()
        )
    finally:
        for connection in silent:
            connection.close()
        _stop_control_server(listener, stopped, server)


def test_stopping_daemon_keeps_serving_authenticated_status(
    tmp_path: Path,
) -> None:
    listener, state, stop_requested, stopped, server = (
        _start_control_server(tmp_path / "daemon.json")
    )
    stop_result: queue.Queue[str] = queue.Queue()
    stopper = threading.Thread(
        target=lambda: stop_result.put(request(state, "STOP"))
    )
    stopper.start()

    try:
        assert stop_requested.wait(timeout=10.0)
        assert request(state, "STATUS") == "stopping"
        stopped.set()
        assert stop_result.get(timeout=2.0) == "stopped"
        stopper.join(timeout=2.0)
        assert stopper.is_alive() is False
    finally:
        stopped.set()
        _stop_control_server(listener, stopped, server)
