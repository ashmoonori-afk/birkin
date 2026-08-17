"""Private Unix-socket and loopback transport primitives."""

from __future__ import annotations

import os
import socket
import struct
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import cast, final

from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    NativeEnvelope,
    NativeProtocolError,
    decode_frame,
    encode_frame,
)
from birkin.native.transport_security import peer_uid, reject_symlinks

_MAX_UNIX_PATH_BYTES = 103
_LISTEN_BACKLOG = 32


@final
@dataclass(slots=True)
class NativeConnection:
    socket: socket.socket
    peer_uid: int | None
    _send_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )

    def __enter__(self) -> NativeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.socket.close()

    def receive(self) -> NativeEnvelope:
        return receive_frame(self.socket)

    def send(self, envelope: NativeEnvelope) -> None:
        with self._send_lock:
            self.socket.sendall(encode_frame(envelope))

    def interrupt(self) -> None:
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


@final
class NativeListener:
    """A bounded local listener with explicit transport identity."""

    def __init__(
        self,
        listener: socket.socket,
        *,
        transport: str,
        socket_path: Path | None,
    ) -> None:
        self._listener = listener
        self.transport = transport
        self.socket_path = socket_path
        self._closed = False

    @classmethod
    def uds(cls, socket_path: Path) -> NativeListener:
        if len(os.fsencode(socket_path)) > _MAX_UNIX_PATH_BYTES:
            raise NativeProtocolError(
                "E_SOCKET_PATH_TOO_LONG",
                "Unix socket path exceeds the platform limit",
            )
        reject_symlinks(socket_path)
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(socket_path.parent, 0o700)
        reject_symlinks(socket_path)
        if socket_path.exists():
            cls._remove_stale_socket(socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(socket_path))
            os.chmod(socket_path, 0o600)
            listener.listen(_LISTEN_BACKLOG)
        except BaseException:
            listener.close()
            socket_path.unlink(missing_ok=True)
            raise
        return cls(listener, transport="uds", socket_path=socket_path)

    @classmethod
    def loopback(cls) -> NativeListener:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        listener.bind(("127.0.0.1", 0))
        listener.listen(_LISTEN_BACKLOG)
        return cls(listener, transport="loopback", socket_path=None)

    @property
    def address(self) -> tuple[str, int]:
        raw_address = cast(object, self._listener.getsockname())
        if not isinstance(raw_address, tuple):
            raise NativeProtocolError(
                "E_TRANSPORT",
                "listener does not have an IP address",
            )
        address = cast(tuple[object, ...], raw_address)
        if len(address) < 2:
            raise NativeProtocolError(
                "E_TRANSPORT",
                "listener does not have an IP address",
            )
        host, port = address[:2]
        if not isinstance(host, str) or not isinstance(port, int):
            raise NativeProtocolError(
                "E_TRANSPORT",
                "listener address is malformed",
            )
        return host, port

    def __enter__(self) -> NativeListener:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def accept(self, *, expected_uid: int | None = None) -> NativeConnection:
        connection = self._listener.accept()[0]
        accepted_uid = (
            peer_uid(connection)
            if self.transport == "uds"
            else None
        )
        if expected_uid is not None and accepted_uid != expected_uid:
            connection.close()
            raise NativeProtocolError(
                "E_PEER_UID_MISMATCH",
                "Unix socket peer does not match the server user",
            )
        return NativeConnection(socket=connection, peer_uid=accepted_uid)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._listener.close()
        if self.socket_path is not None:
            self.socket_path.unlink(missing_ok=True)

    @staticmethod
    def _remove_stale_socket(socket_path: Path) -> None:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.1)
            probe.connect(str(socket_path))
        except OSError:
            socket_path.unlink(missing_ok=True)
        else:
            raise NativeProtocolError(
                "E_ALREADY_RUNNING",
                "a native bridge already owns this socket",
            )
        finally:
            probe.close()


def receive_frame(connection: socket.socket) -> NativeEnvelope:
    """Read one frame while bounding its body before allocation."""

    header = _receive_exact(connection, 4)
    declared = struct.unpack(">I", header)[0]
    if declared > MAX_FRAME_BYTES:
        raise NativeProtocolError(
            "E_FRAME_TOO_LARGE",
            "native frame exceeds limit",
        )
    body = _receive_exact(connection, declared)
    return decode_frame(header + body)


def _receive_exact(connection: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        try:
            chunk = connection.recv(remaining)
        except OSError as exc:
            raise NativeProtocolError(
                "E_FRAME_INCOMPLETE",
                "connection closed before a complete frame arrived",
            ) from exc
        if not chunk:
            raise NativeProtocolError(
                "E_FRAME_INCOMPLETE",
                "connection closed during a frame",
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
