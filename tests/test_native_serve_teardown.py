from __future__ import annotations

import socket
import threading
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.workspace import WorkspaceService
from birkin.workspace.contracts import JsonValue
from tests.native_bridge_support import (
    command_body,
    envelope,
    handshake,
    local_peer_uid,
    serve,
)


def test_peer_loss_terminates_connection_while_command_is_blocked(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked_chat(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        entered.set()
        if not release.wait(timeout=10):
            raise AssertionError("test did not release blocked command")
        return {"reply": str(payload["text"])}

    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": blocked_chat},
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
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        token = handshake(client)
        client.sendall(encode_frame(envelope(
            "command",
            frame_id="disconnected-command-frame",
            body=command_body(
                token,
                command_id="disconnected-command",
                cursor=0,
                text="wait for peer loss",
            ),
        )))
        assert entered.wait(timeout=10)

        client.close()
        thread.join(timeout=10)

        assert not thread.is_alive()
    finally:
        release.set()
        client.close()
        thread.join(timeout=10)
    assert errors == []


def test_serve_connection_owns_full_teardown_of_a_wedged_connection(
    tmp_path: Path,
) -> None:
    mutation_started = threading.Event()
    release_mutation = threading.Event()
    cleanup_completed = threading.Event()
    cleanup_calls = 0

    def blocked_chat(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        mutation_started.set()
        assert release_mutation.wait(timeout=10)
        return {"reply": str(payload["text"])}

    def cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        cleanup_completed.set()

    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": blocked_chat},
    )
    bridge = NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
        on_disconnect=cleanup,
    )
    server_socket, client = socket.socketpair()
    client.settimeout(2)
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
    try:
        token = handshake(client)
        client.sendall(encode_frame(envelope(
            "command",
            frame_id="wedged-command-frame",
            body=command_body(
                token,
                command_id="wedged-command",
                cursor=0,
                text="disconnect before receipt",
            ),
        )))
        assert mutation_started.wait(timeout=5)

        client.close()
        release_mutation.set()
        thread.join(timeout=10)

        assert not thread.is_alive()
        assert cleanup_completed.wait(timeout=5)
        assert cleanup_calls == 1
        assert not [
            candidate
            for candidate in threading.enumerate()
            if candidate.name == "birkin-native-writer"
        ]
    finally:
        release_mutation.set()
        client.close()
        thread.join(timeout=10)
    assert errors == []
