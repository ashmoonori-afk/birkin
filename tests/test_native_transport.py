from __future__ import annotations

import os
import socket
import stat
import struct
import threading
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir

import pytest

from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    NativeEnvelope,
    NativeProtocolError,
    encode_frame,
)
from birkin.native.transport import (
    NativeConnection,
    NativeListener,
    receive_frame,
)

_HAS_POSIX_PEER_UID = hasattr(os, "geteuid")
_TEMP_ROOT = str(Path(gettempdir()).resolve())


@pytest.fixture
def uds_path() -> Iterator[Path]:
    with TemporaryDirectory(prefix="birkin-native-", dir=_TEMP_ROOT) as root:
        yield Path(root) / "run" / "bridge.sock"


@pytest.mark.skipif(
    not _HAS_POSIX_PEER_UID,
    reason="Unix peer credentials require a POSIX host",
)
def test_uds_listener_is_private_and_authenticates_same_user(
    uds_path: Path,
) -> None:
    with NativeListener.uds(uds_path) as listener:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(uds_path))
            with listener.accept(expected_uid=os.geteuid()) as connection:
                assert connection.peer_uid == os.geteuid()
        assert stat.S_IMODE(uds_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(uds_path.stat().st_mode) == 0o600

    assert uds_path.exists() is False


@pytest.mark.skipif(
    not _HAS_POSIX_PEER_UID,
    reason="Unix peer credentials require a POSIX host",
)
def test_uds_listener_rejects_mismatched_peer_uid(uds_path: Path) -> None:
    with NativeListener.uds(uds_path) as listener:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(uds_path))
            with pytest.raises(NativeProtocolError) as exc_info:
                _ = listener.accept(expected_uid=os.geteuid() + 1)

    assert exc_info.value.code == "E_PEER_UID_MISMATCH"


def test_loopback_listener_binds_private_ipv4_only() -> None:
    with NativeListener.loopback() as listener:
        host, port = listener.address

        assert host == "127.0.0.1"
        assert port > 0
        with socket.create_connection(listener.address, timeout=1):
            with listener.accept() as connection:
                assert connection.peer_uid is None


def test_transport_rejects_oversized_frame_before_body_read() -> None:
    server, client = socket.socketpair()
    try:
        client.sendall(struct.pack(">I", MAX_FRAME_BYTES + 1))

        with pytest.raises(NativeProtocolError) as exc_info:
            _ = receive_frame(server)

        assert exc_info.value.code == "E_FRAME_TOO_LARGE"
    finally:
        server.close()
        client.close()


def test_transport_accepts_exact_maximum_frame() -> None:
    envelope = NativeEnvelope.parse(
        {
            "protocol": "birkin-local-1",
            "protocol_version": 1,
            "kind": "ping",
            "id": "ping-max",
            "in_reply_to": None,
            "body": {"sent_at": "now"},
        }
    )
    encoded = encode_frame(envelope)
    body = encoded[4:] + b" " * (MAX_FRAME_BYTES - len(encoded[4:]))
    server, client = socket.socketpair()
    try:
        sender = threading.Thread(
            target=client.sendall,
            args=(struct.pack(">I", len(body)) + body,),
            daemon=True,
        )
        sender.start()

        decoded = receive_frame(server)
        sender.join(timeout=2)

        assert decoded.id == "ping-max"
        assert sender.is_alive() is False
    finally:
        server.close()
        client.close()


def test_a_peer_that_stops_reading_cannot_wedge_a_send() -> None:
    """Given a peer that never reads, When the socket buffers fill, Then the
    send fails on its deadline instead of holding the send gate forever."""
    writer, silent_peer = socket.socketpair()
    writer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    silent_peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    connection = NativeConnection(writer, None, send_timeout=0.25)
    frame = NativeEnvelope.parse({
        "protocol": "birkin-local-1",
        "protocol_version": 1,
        "kind": "event",
        "id": "wedge-1",
        "in_reply_to": None,
        "body": {"text": "x" * 200_000},
    })
    try:
        with pytest.raises(NativeProtocolError) as wedged:
            for _ in range(50):
                connection.send(frame)
        assert wedged.value.code == "E_SEND_TIMEOUT"
    finally:
        connection.close()
        silent_peer.close()


def test_uds_listener_rejects_overlong_socket_path(tmp_path: Path) -> None:
    socket_path = tmp_path / ("x" * 120) / "bridge.sock"

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = NativeListener.uds(socket_path)

    assert exc_info.value.code == "E_SOCKET_PATH_TOO_LONG"


def test_uds_listener_rejects_symlinked_parent() -> None:
    with TemporaryDirectory(prefix="birkin-native-", dir=_TEMP_ROOT) as root:
        actual = Path(root) / "actual"
        actual.mkdir()
        linked = Path(root) / "linked"
        linked.symlink_to(actual, target_is_directory=True)

        with pytest.raises(NativeProtocolError) as exc_info:
            _ = NativeListener.uds(linked / "native.sock")

    assert exc_info.value.code == "E_SOCKET_PATH"


def test_uds_listener_rejects_symlinked_socket_path() -> None:
    with TemporaryDirectory(prefix="birkin-native-", dir=_TEMP_ROOT) as root:
        target = Path(root) / "target.sock"
        target.touch()
        linked = Path(root) / "native.sock"
        linked.symlink_to(target)

        with pytest.raises(NativeProtocolError) as exc_info:
            _ = NativeListener.uds(linked)

    assert exc_info.value.code == "E_SOCKET_PATH"
