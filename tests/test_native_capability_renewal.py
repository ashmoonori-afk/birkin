from __future__ import annotations

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
    local_peer_uid,
    serve,
)


class _Clock:
    def __init__(self) -> None:
        self.current: datetime = datetime(2026, 8, 21, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def test_queued_previous_token_survives_in_band_renewal(tmp_path: Path) -> None:
    clock = _Clock()
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={},
    )
    capabilities = BootstrapSecretStore(
        tmp_path / "native",
        now=clock,
        capability_ttl=timedelta(seconds=9),
        capability_max_age=timedelta(seconds=30),
    )
    bridge = NativeBridgeServer(
        source,
        capabilities=capabilities,
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
        previous_token = handshake(client)
        clock.advance(7)
        sent_at = clock().isoformat()
        client.sendall(
            encode_frame(envelope(
                "ping",
                frame_id="renew-trigger",
                body={
                    "session_capability": previous_token,
                    "sent_at": sent_at,
                },
            ))
            + encode_frame(envelope(
                "ping",
                frame_id="queued-previous",
                body={
                    "session_capability": previous_token,
                    "sent_at": sent_at,
                },
            ))
        )

        renewed = receive_frame(client)
        trigger_pong = receive_frame(client)
        queued_pong = receive_frame(client)
        assert renewed.kind == "capability.renewed"
        assert trigger_pong.in_reply_to == "renew-trigger"
        assert queued_pong.kind == "pong"
        assert queued_pong.in_reply_to == "queued-previous"
        current_token = renewed.body["token"]
        assert isinstance(current_token, str)
        client.sendall(encode_frame(envelope(
            "ping",
            frame_id="current-token",
            body={
                "session_capability": current_token,
                "sent_at": sent_at,
            },
        )))
        current_pong = receive_frame(client)

        assert current_pong.kind == "pong"
        assert current_pong.in_reply_to == "current-token"
        assert capabilities.active_session_count() == 2
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_reconnect_does_not_inherit_capability_overlap(tmp_path: Path) -> None:
    clock = _Clock()
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={},
    )
    capabilities = BootstrapSecretStore(
        tmp_path / "native",
        now=clock,
        capability_ttl=timedelta(seconds=9),
        capability_max_age=timedelta(seconds=30),
    )
    bridge = NativeBridgeServer(
        source,
        capabilities=capabilities,
        instance_id="instance-1",
        server_version="1.0.0",
    )
    first_server, first_client = socket.socketpair()
    first_thread, first_errors = serve(
        bridge,
        first_server,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    previous_token = handshake(first_client)
    clock.advance(7)
    first_client.sendall(encode_frame(envelope(
        "ping",
        frame_id="renew-before-reconnect",
        body={
            "session_capability": previous_token,
            "sent_at": clock().isoformat(),
        },
    )))
    assert receive_frame(first_client).kind == "capability.renewed"
    assert receive_frame(first_client).kind == "pong"
    first_client.close()
    first_thread.join(timeout=2)

    assert first_errors == []
    assert capabilities.active_session_count() == 0

    second_server, second_client = socket.socketpair()
    second_thread, second_errors = serve(
        bridge,
        second_server,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        _ = handshake(second_client)
        second_client.sendall(encode_frame(envelope(
            "ping",
            frame_id="stale-connection-token",
            body={
                "session_capability": previous_token,
                "sent_at": clock().isoformat(),
            },
        )))
        refusal = receive_frame(second_client)

        assert refusal.kind == "error"
        assert refusal.body["code"] == "E_CAPABILITY_INVALID"
    finally:
        second_client.close()
        second_thread.join(timeout=2)
    assert second_errors == []
