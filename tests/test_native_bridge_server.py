from __future__ import annotations

import os
import socket
from pathlib import Path

from birkin.native.protocol import (
    encode_frame,
)
from birkin.native.transport import receive_frame
from tests.native_bridge_support import envelope, hello, serve, server


def test_uds_handshake_and_initial_snapshot(tmp_path: Path) -> None:
    bridge, _capabilities = server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)

        client.sendall(
            encode_frame(
                envelope(
                    "subscribe",
                    frame_id="subscribe-1",
                    body={
                        "session_id": "session-1",
                        "after_cursor": 0,
                        "known_instance_id": None,
                        "session_capability": token,
                        "surfaces": {},
                    },
                )
            )
        )
        snapshot = receive_frame(client)

        assert ready.kind == "ready"
        assert snapshot.kind == "snapshot"
        assert snapshot.body["session_id"] == "session-1"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_subscribe_rejects_invalid_session_capability(tmp_path: Path) -> None:
    bridge, _capabilities = server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
        _ = receive_frame(client)
        client.sendall(
            encode_frame(
                envelope(
                    "subscribe",
                    frame_id="subscribe-invalid",
                    body={
                        "session_id": "session-1",
                        "after_cursor": 0,
                        "known_instance_id": None,
                        "session_capability": "wrong",
                        "surfaces": {},
                    },
                )
            )
        )
        error = receive_frame(client)
        assert error.kind == "error"
        assert error.body["code"] == "E_CAPABILITY_INVALID"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_authenticated_command_returns_public_receipt(tmp_path: Path) -> None:
    bridge, _capabilities = server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)
        client.sendall(
            encode_frame(
                envelope(
                    "subscribe",
                    frame_id="subscribe-1",
                    body={
                        "session_id": "session-1",
                        "after_cursor": 0,
                        "known_instance_id": None,
                        "session_capability": token,
                        "surfaces": {},
                    },
                )
            )
        )
        _ = receive_frame(client)
        client.sendall(
            encode_frame(
                envelope(
                    "command",
                    frame_id="command-1",
                    body={
                        "session_capability": token,
                        "command": {
                            "protocol_version": 1,
                            "command_id": "macos-send-1",
                            "expected_cursor": 0,
                            "type": "chat.send",
                            "payload": {"text": "hello"},
                            "client_context": {
                                "surface": "macos",
                                "view_id": "main",
                            },
                        },
                    },
                )
            )
        )
        receipt = receive_frame(client)

        assert receipt.kind == "receipt"
        assert receipt.in_reply_to == "command-1"
        assert receipt.body["outcome"] == "accepted"
        assert "fingerprint" not in receipt.body
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []
