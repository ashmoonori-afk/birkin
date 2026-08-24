"""Deadline-bounded native connection framing."""

from __future__ import annotations

import select
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from types import TracebackType
from typing import final

from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    NativeEnvelope,
    NativeProtocolError,
    decode_frame,
    encode_frame,
)

DEFAULT_SEND_TIMEOUT_SECONDS = 30.0


@final
@dataclass(slots=True)
class NativeConnection:
    """One non-blocking native connection with per-frame deadlines."""

    socket: socket.socket
    peer_uid: int | None
    send_timeout: float = DEFAULT_SEND_TIMEOUT_SECONDS
    _read_deadline: float | None = field(default=None, repr=False)
    _send_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )

    def __post_init__(self) -> None:
        # Both directions are select-driven, so the socket stays non-blocking.
        # A per-socket timeout is shared state between the reader and writer
        # threads; a deadline carried per read is not.
        self.socket.setblocking(False)

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

    def set_read_deadline(self, seconds: float | None) -> None:
        """Bound how long one whole frame may take to arrive, or wait forever."""
        self._read_deadline = seconds

    def receive(self) -> NativeEnvelope:
        deadline = (
            time.monotonic() + self._read_deadline
            if self._read_deadline is not None
            else None
        )
        header = self._receive_exact(4, deadline)
        declared = struct.unpack(">I", header)[0]
        if declared > MAX_FRAME_BYTES:
            raise NativeProtocolError(
                "E_FRAME_TOO_LARGE",
                "native frame exceeds limit",
            )
        body = self._receive_exact(declared, deadline)
        return decode_frame(header + body)

    def _receive_exact(self, length: int, deadline: float | None) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = self._receive_some(remaining, deadline)
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _receive_some(self, size: int, deadline: float | None) -> bytes:
        while True:
            try:
                chunk = self.socket.recv(size)
            except BlockingIOError:
                self._await_readable(deadline)
                continue
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
            return chunk

    def _await_readable(self, deadline: float | None) -> None:
        timeout = None if deadline is None else deadline - time.monotonic()
        try:
            readable = (
                select.select([self.socket], [], [], timeout)[0]
                if timeout is None or timeout > 0
                else []
            )
        except (OSError, ValueError) as exc:
            # A socket closed underneath a waiting reader is an incomplete frame.
            raise NativeProtocolError(
                "E_FRAME_INCOMPLETE",
                "connection closed before a complete frame arrived",
            ) from exc
        if not readable:
            raise NativeProtocolError(
                "E_FRAME_INCOMPLETE",
                "peer did not complete a frame within the deadline",
            )

    def send(self, envelope: NativeEnvelope) -> None:
        with self._send_lock:
            self._send_all(encode_frame(envelope))

    def _send_all(self, payload: bytes) -> None:
        """Write one whole frame within a bounded deadline."""
        view = memoryview(payload)
        deadline = time.monotonic() + self.send_timeout
        while view:
            try:
                view = view[self.socket.send(view):]
            except BlockingIOError:
                self._await_writable(deadline)

    def _await_writable(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        writable = (
            select.select([], [self.socket], [], remaining)[1]
            if remaining > 0
            else []
        )
        if not writable:
            raise NativeProtocolError(
                "E_SEND_TIMEOUT",
                "peer stopped reading the connection",
            )

    def interrupt(self) -> None:
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
