"""Bounded authenticated control server for the voice daemon."""

from __future__ import annotations

import json
import selectors
import socket
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from .daemon_state import DaemonState
from .daemon_storage import update_state

_MAX_MESSAGE = 4096
_MAX_CLIENTS = 32
_CLIENT_TIMEOUT_SECONDS = 2.0
_IDLE_POLL_SECONDS = 0.2
_STOP_RESPONSE_TIMEOUT_SECONDS = 32.0


@dataclass(slots=True)
class _Client:
    socket: socket.socket
    deadline: float
    buffer: bytearray = field(default_factory=bytearray)


def control_loop(
    listener: socket.socket,
    state_path: Path,
    initial: DaemonState,
    stop_requested: threading.Event,
    stopped: threading.Event,
) -> None:
    selector = selectors.DefaultSelector()
    clients: dict[socket.socket, _Client] = {}
    state = initial
    stop_responder: threading.Thread | None = None
    listener.setblocking(False)
    selector.register(listener, selectors.EVENT_READ)
    try:
        while not stopped.is_set():
            _expire_clients(selector, clients)
            try:
                events = selector.select(_next_timeout(clients))
            except (OSError, ValueError):
                break
            for key, _mask in sorted(
                events,
                key=lambda event: event[0].data is None,
            ):
                if key.data is None:
                    if not _accept_client(selector, clients, listener):
                        return
                    continue
                client = key.data
                if not isinstance(client, _Client):
                    continue
                message = _read_message(selector, clients, client)
                if message is None:
                    continue
                state, wait_for_stop = _handle_message(
                    client.socket,
                    state_path,
                    state,
                    stop_requested,
                    message,
                )
                _forget_client(selector, clients, client)
                if wait_for_stop:
                    client.socket.setblocking(True)
                    stop_responder = threading.Thread(
                        target=_respond_after_stop,
                        args=(client.socket, stopped),
                        name="birkin-voice-stop-response",
                        daemon=True,
                    )
                    stop_responder.start()
                else:
                    client.socket.close()
    finally:
        for client in tuple(clients.values()):
            _close_client(selector, clients, client)
        selector.close()
        if stop_responder is not None:
            stop_responder.join(timeout=_STOP_RESPONSE_TIMEOUT_SECONDS)


def _accept_client(
    selector: selectors.BaseSelector,
    clients: dict[socket.socket, _Client],
    listener: socket.socket,
) -> bool:
    try:
        connection, _address = listener.accept()
    except BlockingIOError:
        return True
    except OSError:
        return False
    connection.setblocking(False)
    if len(clients) >= _MAX_CLIENTS:
        oldest = min(clients.values(), key=lambda client: client.deadline)
        _close_client(selector, clients, oldest)
    client = _Client(
        socket=connection,
        deadline=time.monotonic() + _CLIENT_TIMEOUT_SECONDS,
    )
    clients[connection] = client
    selector.register(connection, selectors.EVENT_READ, client)
    return True


def _read_message(
    selector: selectors.BaseSelector,
    clients: dict[socket.socket, _Client],
    client: _Client,
) -> bytes | None:
    try:
        chunk = client.socket.recv(_MAX_MESSAGE + 1 - len(client.buffer))
    except (BlockingIOError, OSError):
        return None
    if not chunk:
        _close_client(selector, clients, client)
        return None
    client.buffer.extend(chunk)
    if b"\n" not in client.buffer:
        if len(client.buffer) > _MAX_MESSAGE:
            _safe_respond(client.socket, "invalid")
            _close_client(selector, clients, client)
        return None
    return bytes(client.buffer).split(b"\n", 1)[0]


def _handle_message(
    connection: socket.socket,
    state_path: Path,
    state: DaemonState,
    stop_requested: threading.Event,
    message: bytes,
) -> tuple[DaemonState, bool]:
    try:
        value = json.loads(message)
    except (ValueError, json.JSONDecodeError):
        _safe_respond(connection, "invalid")
        return state, False
    if (
        not isinstance(value, dict)
        or value.get("instance_id") != state.instance_id
        or value.get("token") != state.token
    ):
        _safe_respond(connection, "unauthorized")
        return state, False
    action = value.get("action")
    if action == "STATUS":
        _safe_respond(connection, state.status)
        return state, False
    if action != "STOP":
        _safe_respond(connection, "invalid")
        return state, False
    if state.status == "stopping":
        _safe_respond(connection, "stopping")
        return state, False
    state = replace(state, status="stopping")
    update_state(state_path, state)
    stop_requested.set()
    return state, True


def _expire_clients(
    selector: selectors.BaseSelector,
    clients: dict[socket.socket, _Client],
) -> None:
    now = time.monotonic()
    for client in tuple(clients.values()):
        if client.deadline <= now:
            _safe_respond(client.socket, "invalid")
            _close_client(selector, clients, client)


def _next_timeout(clients: dict[socket.socket, _Client]) -> float:
    """Never wait indefinitely, so the loop can notice shutdown by itself.

    Closing the listener does not reliably wake a blocked ``select`` on POSIX,
    which left this thread alive after ``serve`` had already returned.
    """
    if not clients:
        return _IDLE_POLL_SECONDS
    deadline = min(client.deadline for client in clients.values())
    return max(0.0, min(_IDLE_POLL_SECONDS, deadline - time.monotonic()))


def _forget_client(
    selector: selectors.BaseSelector,
    clients: dict[socket.socket, _Client],
    client: _Client,
) -> None:
    clients.pop(client.socket, None)
    try:
        selector.unregister(client.socket)
    except (KeyError, ValueError):
        return


def _close_client(
    selector: selectors.BaseSelector,
    clients: dict[socket.socket, _Client],
    client: _Client,
) -> None:
    _forget_client(selector, clients, client)
    client.socket.close()


def _respond_after_stop(
    connection: socket.socket,
    stopped: threading.Event,
) -> None:
    with connection:
        status = "stopped" if stopped.wait(timeout=30.0) else "stopping"
        _safe_respond(connection, status)


def _safe_respond(connection: socket.socket, status: str) -> None:
    try:
        connection.sendall(
            json.dumps({"status": status}).encode("utf-8") + b"\n"
        )
    except OSError:
        return
