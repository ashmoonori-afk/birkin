from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import NativeEnvelope, encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import (
    envelope,
    local_peer_uid,
    serve,
    server_with_source,
)


class _Clock:
    def __init__(self) -> None:
        self.current: datetime = datetime(2026, 8, 21, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current


def _hello(*, surface: str, view_id: str) -> NativeEnvelope:
    return envelope(
        "hello",
        frame_id="hello-1",
        body={
            "client": "birkin-macos",
            "client_version": "1.0.0",
            "client_build": "100",
            "supported_protocol_versions": [1],
            "surface": surface,
            "view_id": view_id,
            "bootstrap_secret": None,
        },
    )


def _handshake(client: socket.socket, *, surface: str, view_id: str) -> str:
    client.sendall(encode_frame(_hello(surface=surface, view_id=view_id)))
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
    assert receive_frame(client).kind == "snapshot"
    return token


def _command(
    token: str,
    *,
    frame_id: str,
    command_id: str,
    surface: str,
    view_id: str,
) -> NativeEnvelope:
    return envelope(
        "command",
        frame_id=frame_id,
        body={
            "session_capability": token,
            "command": {
                "protocol_version": 1,
                "command_id": command_id,
                "expected_cursor": 0,
                "type": "chat.send",
                "payload": {"text": command_id},
                "client_context": {"surface": surface, "view_id": view_id},
            },
        },
    )


def test_command_rejects_surface_outside_capability_scope_and_stays_healthy(
    tmp_path: Path,
) -> None:
    bridge, _capabilities, _source = server_with_source(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        token = _handshake(client, surface="macos", view_id="main")
        client.sendall(
            encode_frame(
                _command(
                    token,
                    frame_id="surface-spoof-frame",
                    command_id="surface-spoof",
                    surface="web",
                    view_id="main",
                )
            )
        )
        refusal = receive_frame(client)

        assert refusal.kind == "error"
        assert refusal.body["code"] == "E_CAPABILITY_SCOPE"

        client.sendall(
            encode_frame(
                _command(
                    token,
                    frame_id="matching-frame",
                    command_id="matching-after-refusal",
                    surface="macos",
                    view_id="main",
                )
            )
        )
        receipt = receive_frame(client)
        assert receipt.kind == "receipt"
        assert receipt.body["actor_id"] == "macos:main"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_command_rejects_view_outside_capability_scope(tmp_path: Path) -> None:
    bridge, _capabilities, source = server_with_source(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        token = _handshake(client, surface="macos", view_id="main")
        client.sendall(
            encode_frame(
                _command(
                    token,
                    frame_id="view-spoof-frame",
                    command_id="view-spoof",
                    surface="macos",
                    view_id="admin",
                )
            )
        )
        refusal = receive_frame(client)

        assert refusal.kind == "error"
        assert refusal.body["code"] == "E_CAPABILITY_SCOPE"
        assert source.events() == ()
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_renewed_capability_preserves_command_scope(tmp_path: Path) -> None:
    clock = _Clock()
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": lambda payload: {"reply": payload}},
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
    )
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        token = _handshake(client, surface="macos", view_id="main")
        clock.current += timedelta(seconds=700)
        client.sendall(
            encode_frame(
                envelope(
                    "ping",
                    frame_id="renew-ping",
                    body={
                        "session_capability": token,
                        "sent_at": clock().isoformat(),
                    },
                )
            )
        )
        renewed = receive_frame(client)
        assert renewed.kind == "capability.renewed"
        renewed_token = renewed.body["token"]
        assert isinstance(renewed_token, str)
        assert receive_frame(client).kind == "pong"

        client.sendall(
            encode_frame(
                _command(
                    renewed_token,
                    frame_id="renewed-spoof-frame",
                    command_id="renewed-spoof",
                    surface="macos",
                    view_id="admin",
                )
            )
        )
        refusal = receive_frame(client)
        assert refusal.kind == "error"
        assert refusal.body["code"] == "E_CAPABILITY_SCOPE"
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_matching_command_uses_capability_scope_for_actor(tmp_path: Path) -> None:
    bridge, _capabilities, source = server_with_source(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        token = _handshake(client, surface="web", view_id="workspace-1")
        client.sendall(
            encode_frame(
                _command(
                    token,
                    frame_id="matching-web-frame",
                    command_id="matching-web",
                    surface="web",
                    view_id="workspace-1",
                )
            )
        )
        receipt = receive_frame(client)

        assert receipt.kind == "receipt"
        assert receipt.body["actor_id"] == "web:workspace-1"
        assert {event.actor_id for event in source.events()} == {"web:workspace-1"}
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []
