from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import (
    envelope,
    handshake,
    serve,
    server,
)


class _Clock:
    def __init__(self) -> None:
        self.current: datetime = datetime(
            2026,
            8,
            17,
            tzinfo=timezone.utc,
        )

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def test_disconnect_revokes_session_capability(tmp_path: Path) -> None:
    bridge, capabilities = server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    token = handshake(client)

    client.close()
    thread.join(timeout=2)

    assert token
    assert capabilities.active_session_count() == 0
    assert errors == []


def test_ping_without_capability_fails_closed(tmp_path: Path) -> None:
    bridge, _capabilities = server(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        _ = handshake(client)
        client.sendall(
            encode_frame(
                envelope(
                    "ping",
                    frame_id="ping-1",
                    body={"sent_at": "2026-08-17T00:00:00Z"},
                )
            )
        )
        error = receive_frame(client)

        assert error.kind == "error"
        assert error.body["code"] == "E_BODY"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_near_expiry_ping_renews_capability_in_band(tmp_path: Path) -> None:
    clock = _Clock()
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={},
    )
    capabilities = BootstrapSecretStore(
        tmp_path / "native",
        now=clock,
        capability_ttl=timedelta(seconds=900),
        capability_max_age=timedelta(hours=8),
    )
    bridge = NativeBridgeServer(
        source,
        capabilities=capabilities,
        instance_id="instance-1",
        server_version="1.0.0",
        command_types=set(),
    )
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=os.geteuid(),
    )
    try:
        token = handshake(client)
        clock.advance(700)
        client.sendall(
            encode_frame(
                envelope(
                    "ping",
                    frame_id="ping-1",
                    body={
                        "session_capability": token,
                        "sent_at": clock().isoformat(),
                    },
                )
            )
        )
        renewed = receive_frame(client)
        pong = receive_frame(client)

        assert renewed.kind == "capability.renewed"
        assert isinstance(renewed.body["token"], str)
        assert renewed.body["token"] != token
        assert pong.kind == "pong"
        assert pong.in_reply_to == "ping-1"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []
