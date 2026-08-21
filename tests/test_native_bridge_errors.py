from __future__ import annotations

import socket
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import (
    command_body,
    envelope,
    handshake,
    hello,
    local_peer_uid,
    receive_kind,
    serve,
    server,
    server_with_source,
)


def test_loopback_rejects_invalid_bootstrap_secret(tmp_path: Path) -> None:
    bridge, capabilities = server(tmp_path)
    _ = capabilities.issue()
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="loopback",
        peer_uid=None,
    )
    try:
        hello: dict[str, object] = {
            "client": "birkin-macos",
            "client_version": "1.0.0",
            "client_build": "100",
            "supported_protocol_versions": [1],
            "surface": "macos",
            "view_id": "main",
            "bootstrap_secret": "wrong",
        }
        client.sendall(
            encode_frame(envelope("hello", frame_id="hello-1", body=hello))
        )
        error = receive_kind(client, "error")
        assert error.body["code"] == "E_BOOTSTRAP_INVALID"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_malformed_workspace_command_returns_bounded_error(
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
    try:
        token = handshake(client)
        client.sendall(
            encode_frame(
                envelope(
                    "command",
                    frame_id="command-bad",
                    body={
                        "session_capability": token,
                        "command": {"unexpected": True},
                    },
                )
            )
        )
        error = receive_kind(client, "error")
        assert error.kind == "error"
        assert error.body["code"] == "E_BODY"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_stale_cursor_returns_current_cursor(tmp_path: Path) -> None:
    bridge, _capabilities = server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        token = handshake(client)
        client.sendall(
            encode_frame(
                envelope(
                    "command",
                    frame_id="command-1",
                    body=command_body(
                        token,
                        command_id="send-1",
                        cursor=0,
                        text="first",
                    ),
                )
            )
        )
        _ = receive_frame(client)
        client.sendall(
            encode_frame(
                envelope(
                    "command",
                    frame_id="command-2",
                    body=command_body(
                        token,
                        command_id="send-2",
                        cursor=0,
                        text="stale",
                    ),
                )
            )
        )
        error = receive_kind(client, "error")
        assert error.body["code"] == "E_STALE_CURSOR"
        assert error.body["current_cursor"] == 3
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_command_id_payload_conflict_returns_error(tmp_path: Path) -> None:
    bridge, _capabilities = server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        token = handshake(client)
        client.sendall(
            encode_frame(
                envelope(
                    "command",
                    frame_id="command-1",
                    body=command_body(
                        token,
                        command_id="send-1",
                        cursor=0,
                        text="first",
                    ),
                )
            )
        )
        _ = receive_frame(client)
        client.sendall(
            encode_frame(
                envelope(
                    "command",
                    frame_id="command-2",
                    body=command_body(
                        token,
                        command_id="send-1",
                        cursor=3,
                        text="changed",
                    ),
                )
            )
        )
        error = receive_kind(client, "error")
        assert error.body["code"] == "E_COMMAND_ID_CONFLICT"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_unadvertised_known_command_is_journaled_as_failed(
    tmp_path: Path,
) -> None:
    bridge, _capabilities, source = server_with_source(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        token = handshake(client)
        client.sendall(
            encode_frame(
                envelope(
                    "command",
                    frame_id="command-unsupported",
                    body={
                        "session_capability": token,
                        "command": {
                            "protocol_version": 1,
                            "command_id": "unsupported-1",
                            "expected_cursor": 0,
                            "type": "session.create",
                            "payload": {"session_id": "other"},
                            "client_context": {
                                "surface": "macos",
                                "view_id": "main",
                            },
                        },
                    },
                )
            )
        )
        error = receive_kind(client, "error")
        events = source.events()

        assert error.body["code"] == "E_UNSUPPORTED_COMMAND"
        assert any(
            event.type == "command.failed"
            and event.command_id == "unsupported-1"
            for event in events
        )
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_handler_failure_returns_a_typed_refusal_and_keeps_the_connection(
    tmp_path: Path,
) -> None:
    """Given a command whose canonical handler raises a non-protocol error,
    When it is submitted, Then the client receives a typed refusal and the
    connection still serves the next command."""

    def explode(_payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("canonical handler exploded")

    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={
            "chat.send": explode,
            "chat.steer": lambda payload: {"steered": str(payload["text"])},
        },
    )
    bridge = NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
    )
    server_socket, client = socket.socketpair()
    client.settimeout(10)
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    try:
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)
        client.sendall(encode_frame(envelope(
            "subscribe", frame_id="subscribe-1", body={
                "session_id": "session-1", "after_cursor": 0,
                "known_instance_id": None, "session_capability": token,
                "surfaces": {},
            },
        )))
        assert receive_frame(client).kind == "snapshot"

        client.sendall(encode_frame(envelope(
            "command", frame_id="frame-explode",
            body=command_body(token, command_id="explode", cursor=0, text="boom"),
        )))
        refusal = receive_kind(client, "error")
        assert refusal.body["code"] == "E_COMMAND_FAILED"
        assert refusal.in_reply_to == "frame-explode"

        client.sendall(encode_frame(envelope(
            "ping", frame_id="frame-alive",
            body={"session_capability": token, "sent_at": "2026-08-21T00:00:00Z"},
        )))
        assert receive_kind(client, "pong").in_reply_to == "frame-alive"
    finally:
        client.close()
        server_socket.close()
        thread.join(timeout=5)
    assert errors == []
