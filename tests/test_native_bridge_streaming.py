from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import NativeProtocolError
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceCommand, WorkspaceService
from tests.native_bridge_support import (
    handshake,
    serve,
    server_with_source,
)


def _command(command_id: str, cursor: int) -> WorkspaceCommand:
    return WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": command_id,
            "expected_cursor": cursor,
            "type": "chat.send",
            "payload": {"text": "hello"},
            "client_context": {"surface": "macos", "view_id": "main"},
        }
    )


def test_subscribed_connection_streams_new_workspace_events(
    tmp_path: Path,
) -> None:
    bridge, _capabilities, source = server_with_source(tmp_path)
    server_socket, client = socket.socketpair()
    client.settimeout(1)
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        _ = handshake(client)

        _ = source.submit(
            _command("send-live", 0),
            actor_id="terminal:test",
        )
        event = receive_frame(client)

        assert event.kind == "event"
        assert event.body["cursor"] == 1
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_silent_peer_is_closed_after_heartbeat_deadline(
    tmp_path: Path,
) -> None:
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={},
    )
    bridge = NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
        heartbeat_interval=0.05,
        peer_timeout=0.05,
    )
    server_socket, client = socket.socketpair()
    client.settimeout(1)
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        _ = handshake(client)
        ping = receive_frame(client)
        assert ping.kind == "ping"

        with pytest.raises(NativeProtocolError) as exc_info:
            _ = receive_frame(client)
        assert exc_info.value.code == "E_FRAME_INCOMPLETE"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []
