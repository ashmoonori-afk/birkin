"""Bounded multiplexed readiness authentication for voice workers."""

from __future__ import annotations

import json
import selectors
import socket
import time
from dataclasses import dataclass, field

from .daemon_state import DaemonState

_MAX_MESSAGE = 4096
_MAX_CLIENTS = 32


@dataclass(slots=True)
class _Client:
    socket: socket.socket
    accepted_at: float
    buffer: bytearray = field(default_factory=bytearray)


def await_worker(
    listener: socket.socket,
    token: str,
    timeout: float,
) -> DaemonState:
    selector = selectors.DefaultSelector()
    clients: dict[socket.socket, _Client] = {}
    deadline = time.monotonic() + timeout
    listener.setblocking(False)
    selector.register(listener, selectors.EVENT_READ)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("voice daemon readiness timed out")
            events = selector.select(remaining)
            if not events:
                raise TimeoutError("voice daemon readiness timed out")
            for key, _mask in sorted(
                events,
                key=lambda event: event[0].data is None,
            ):
                if key.data is None:
                    _accept_client(selector, clients, listener)
                    continue
                client = key.data
                if not isinstance(client, _Client):
                    continue
                payload = _read_payload(selector, clients, client)
                if payload is None:
                    continue
                value = _decode(payload)
                _close_client(selector, clients, client)
                if value is None or value.get("token") != token:
                    continue
                error = value.get("error")
                if isinstance(error, str) and error:
                    raise OSError(error)
                return DaemonState.from_mapping(value.get("state"))
    finally:
        for client in tuple(clients.values()):
            _close_client(selector, clients, client)
        selector.close()


def _accept_client(
    selector: selectors.BaseSelector,
    clients: dict[socket.socket, _Client],
    listener: socket.socket,
) -> None:
    try:
        connection, _address = listener.accept()
    except (BlockingIOError, OSError):
        return
    connection.setblocking(False)
    if len(clients) >= _MAX_CLIENTS:
        oldest = min(
            clients.values(),
            key=lambda client: client.accepted_at,
        )
        _close_client(selector, clients, oldest)
    client = _Client(connection, time.monotonic())
    clients[connection] = client
    selector.register(connection, selectors.EVENT_READ, client)


def _read_payload(
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
            _close_client(selector, clients, client)
        return None
    return bytes(client.buffer).split(b"\n", 1)[0]


def _decode(payload: bytes) -> dict[str, object] | None:
    try:
        value = json.loads(payload)
    except (ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _close_client(
    selector: selectors.BaseSelector,
    clients: dict[socket.socket, _Client],
    client: _Client,
) -> None:
    clients.pop(client.socket, None)
    try:
        selector.unregister(client.socket)
    except (KeyError, ValueError):
        pass
    client.socket.close()
