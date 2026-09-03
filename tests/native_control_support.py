from __future__ import annotations

import socket
from collections.abc import Callable, Mapping
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import envelope


def send_command(
    client: socket.socket,
    token: str,
    command_type: str,
    command_id: str,
    cursor: int,
    payload: Mapping[str, object],
    *,
    view_id: str = "main",
) -> None:
    client.sendall(
        encode_frame(
            envelope(
                "command",
                frame_id=command_id,
                body={
                    "session_capability": token,
                    "command": {
                        "protocol_version": 1,
                        "command_id": command_id,
                        "expected_cursor": cursor,
                        "type": command_type,
                        "payload": dict(payload),
                        "client_context": {"surface": "macos", "view_id": view_id},
                    },
                },
            )
        )
    )


def send_goodbye(client: socket.socket, token: str, frame_id: str) -> None:
    client.sendall(
        encode_frame(
            envelope(
                "goodbye",
                frame_id=frame_id,
                body={"session_capability": token},
            )
        )
    )


def bridge(
    tmp_path: Path,
    handlers: Mapping[str, Callable[[dict[str, object]], dict[str, object]]],
    *,
    cleanup: Callable[[], None] | None = None,
) -> tuple[NativeBridgeServer, WorkspaceService]:
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers=handlers,
    )
    return NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
        heartbeat_interval=0.05,
        peer_timeout=0.5,
        on_disconnect=cleanup,
    ), source
