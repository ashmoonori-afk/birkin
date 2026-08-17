from __future__ import annotations

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


def envelope(
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


def hello(*, bootstrap_secret: str | None) -> NativeEnvelope:
    return envelope(
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


def server(
    tmp_path: Path,
) -> tuple[NativeBridgeServer, BootstrapSecretStore]:
    bridge, capabilities, _source = server_with_source(tmp_path)
    return bridge, capabilities


def server_with_source(
    tmp_path: Path,
) -> tuple[NativeBridgeServer, BootstrapSecretStore, WorkspaceService]:
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": lambda payload: {"reply": str(payload["text"])}},
    )
    capabilities = BootstrapSecretStore(tmp_path / "native")
    bridge = NativeBridgeServer(
        source,
        capabilities=capabilities,
        instance_id="instance-1",
        server_version="1.0.0",
        command_types={"chat.send"},
    )
    return bridge, capabilities, source


def serve(
    bridge: NativeBridgeServer,
    connection: socket.socket,
    *,
    transport: str,
    peer_uid: int | None,
) -> tuple[threading.Thread, list[BaseException]]:
    errors: list[BaseException] = []

    def run() -> None:
        try:
            bridge.serve_connection(
                NativeConnection(connection, peer_uid),
                transport=transport,
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, errors


def handshake(client: socket.socket) -> str:
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
    assert snapshot.kind == "snapshot"
    return token


def command_body(
    token: str,
    *,
    command_id: str,
    cursor: int,
    text: str,
) -> dict[str, object]:
    return {
        "session_capability": token,
        "command": {
            "protocol_version": 1,
            "command_id": command_id,
            "expected_cursor": cursor,
            "type": "chat.send",
            "payload": {"text": text},
            "client_context": {"surface": "macos", "view_id": "main"},
        },
    }
