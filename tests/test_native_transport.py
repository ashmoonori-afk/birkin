from __future__ import annotations

import os
import socket
import stat
import struct
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from birkin.native.protocol import MAX_FRAME_BYTES, NativeProtocolError
from birkin.native.transport import NativeListener, receive_frame


@pytest.fixture
def uds_path() -> Iterator[Path]:
    with TemporaryDirectory(prefix="birkin-native-", dir="/tmp") as root:
        yield Path(root) / "run" / "bridge.sock"


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


def test_uds_listener_rejects_overlong_socket_path(tmp_path: Path) -> None:
    socket_path = tmp_path / ("x" * 120) / "bridge.sock"

    with pytest.raises(NativeProtocolError) as exc_info:
        _ = NativeListener.uds(socket_path)

    assert exc_info.value.code == "E_SOCKET_PATH_TOO_LONG"
