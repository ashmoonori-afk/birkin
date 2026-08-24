from __future__ import annotations

import socket
import struct
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import (
    encode_frame,
)
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import (
    envelope,
    hello,
    local_peer_uid,
    serve,
    server,
)


def test_pre_auth_deep_json_is_refused_and_bridge_serves_next_connection(
    tmp_path: Path,
) -> None:
    bridge, _capabilities = server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    nested = "[" * 20_000 + "0" + "]" * 20_000
    text = (
        '{"protocol":"birkin-local-1","protocol_version":1,'
        '"kind":"hello","id":"deep-json","in_reply_to":null,'
        f'"body":{{"nested":{nested}}}}}'
    )
    body = text.encode()
    try:
        client.sendall(struct.pack(">I", len(body)) + body)
        refused = receive_frame(client)
        assert refused.kind == "error"
        assert refused.body["code"] == "E_JSON_DEPTH"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []

    next_server_socket, next_client = socket.socketpair()
    next_thread, next_errors = serve(
        bridge,
        next_server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        next_client.sendall(encode_frame(hello(bootstrap_secret=None)))
        assert receive_frame(next_client).kind == "ready"
    finally:
        next_client.close()
        next_thread.join(timeout=2)
    assert next_errors == []


def test_uds_handshake_and_initial_snapshot(tmp_path: Path) -> None:
    bridge, _capabilities = server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
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
        peer_uid=local_peer_uid(),
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
        peer_uid=local_peer_uid(),
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


def test_ready_advertises_authority_handlers_not_caller_claims(
    tmp_path: Path,
) -> None:
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": lambda payload: {"reply": payload}},
    )
    bridge = NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
    )
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capabilities = ready.body["capabilities"]

        assert isinstance(capabilities, dict)
        assert capabilities["commands"] == ["chat.send"]
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []
