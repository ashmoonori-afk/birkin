from __future__ import annotations

import socket
from pathlib import Path

from birkin.native.protocol import encode_frame
from birkin.native.transport import receive_frame
from tests.native_bridge_support import (
    command_body,
    envelope,
    handshake,
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
