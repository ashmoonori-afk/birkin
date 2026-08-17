from __future__ import annotations

import os
import socket
import threading
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import (
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
    NativeEnvelope,
    encode_frame,
)
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import NativeConnection, receive_frame
from birkin.workspace import WorkspaceService


def _envelope(
    kind: str,
    *,
    frame_id: str,
    body: dict[str, object],
    in_reply_to: str | None = None,
) -> NativeEnvelope:
    return NativeEnvelope.parse(
        {
            "protocol": NATIVE_PROTOCOL_NAME,
            "protocol_version": NATIVE_PROTOCOL_VERSION,
            "kind": kind,
            "id": frame_id,
            "in_reply_to": in_reply_to,
            "body": body,
        }
    )


def _hello(*, bootstrap_secret: str | None) -> NativeEnvelope:
    return _envelope(
        "hello",
        frame_id="hello-1",
        body={
            "client": "birkin-macos",
            "client_version": "1.0.0",
            "client_build": "100",
            "supported_protocol_versions": [NATIVE_PROTOCOL_VERSION],
            "surface": "macos",
            "view_id": "main",
            "bootstrap_secret": bootstrap_secret,
        },
    )


def _server(
    tmp_path: Path,
) -> tuple[NativeBridgeServer, BootstrapSecretStore]:
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": lambda payload: {"reply": str(payload["text"])}},
    )
    capabilities = BootstrapSecretStore(tmp_path / "native")
    return (
        NativeBridgeServer(
            source,
            capabilities=capabilities,
            instance_id="instance-1",
            server_version="1.0.0",
            command_types={"chat.send"},
        ),
        capabilities,
    )


def _serve(
    server: NativeBridgeServer,
    connection: socket.socket,
    *,
    transport: str,
    peer_uid: int | None,
) -> tuple[threading.Thread, list[BaseException]]:
    errors: list[BaseException] = []

    def run() -> None:
        try:
            server.serve_connection(
                NativeConnection(connection, peer_uid),
                transport=transport,
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, errors


def test_uds_handshake_and_initial_snapshot(tmp_path: Path) -> None:
    server, _capabilities = _server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = _serve(
        server,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        client.sendall(encode_frame(_hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)

        client.sendall(
            encode_frame(
                _envelope(
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


def test_loopback_rejects_invalid_bootstrap_secret(tmp_path: Path) -> None:
    server, capabilities = _server(tmp_path)
    _ = capabilities.issue()
    server_socket, client = socket.socketpair()
    thread, errors = _serve(
        server,
        server_socket,
        transport="loopback",
        peer_uid=None,
    )
    try:
        client.sendall(encode_frame(_hello(bootstrap_secret="wrong")))
        error = receive_frame(client)
        assert error.kind == "error"
        assert error.body["code"] == "E_BOOTSTRAP_INVALID"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_subscribe_rejects_invalid_session_capability(tmp_path: Path) -> None:
    server, _capabilities = _server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = _serve(
        server,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        client.sendall(encode_frame(_hello(bootstrap_secret=None)))
        _ = receive_frame(client)
        client.sendall(
            encode_frame(
                _envelope(
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
    server, _capabilities = _server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = _serve(
        server,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        client.sendall(encode_frame(_hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)
        client.sendall(
            encode_frame(
                _envelope(
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
                _envelope(
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
