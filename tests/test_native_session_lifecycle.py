from __future__ import annotations

import socket
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceHub
from tests.native_bridge_support import envelope, hello, local_peer_uid, receive_kind, serve


def _server(tmp_path: Path) -> tuple[NativeBridgeServer, WorkspaceHub]:
    hub = WorkspaceHub(
        root=tmp_path / "workspace",
        handlers={"chat.send": lambda payload: {"reply": payload["text"]}},
    )
    session, _ = hub.create("session-1")
    bridge = NativeBridgeServer(
        session.service,
        session_authority=hub,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
    )
    return bridge, hub


def _connect(
    bridge: NativeBridgeServer,
) -> tuple[socket.socket, str, object, list[BaseException]]:
    server_socket, client = socket.socketpair()
    thread, errors = serve(
        bridge,
        server_socket,
        transport="uds",
        peer_uid=local_peer_uid(),
    )
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
    assert receive_kind(client, "snapshot").kind == "snapshot"
    return client, token, thread, errors


def _send(
    client: socket.socket,
    token: str,
    command_type: str,
    command_id: str,
    cursor: int,
    payload: dict[str, object],
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
                        "payload": payload,
                        "client_context": {"surface": "macos", "view_id": "main"},
                    },
                },
            )
        )
    )


def _receive_event_type(client: socket.socket, event_type: str):  # type: ignore[no-untyped-def]
    for _ in range(8):
        event = receive_kind(client, "event")
        if event.body["type"] == event_type:
            return event
    raise AssertionError(f"did not receive event {event_type}")


def test_session_create_over_socket_emits_event_and_updates_projection(
    tmp_path: Path,
) -> None:
    bridge, hub = _server(tmp_path)
    client, token, thread, errors = _connect(bridge)
    try:
        _send(client, token, "session.create", "create-1", 0, {"session_id": "second"})
        receipt = receive_kind(client, "receipt")
        event = _receive_event_type(client, "session.created")

        assert receipt.body["state"] == "completed"
        assert event.body["type"] == "session.created"
        assert hub.get("second") is not None
        assert hub.snapshot().cursor == 4
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []


def test_session_select_over_socket_emits_event_and_changes_projection(
    tmp_path: Path,
) -> None:
    bridge, hub = _server(tmp_path)
    _second, _ = hub.create("second")
    client, token, thread, errors = _connect(bridge)
    try:
        _send(client, token, "session.select", "select-1", 0, {"session_id": "second"})
        receipt = receive_kind(client, "receipt")
        event = _receive_event_type(client, "session.selected")

        assert receipt.body["state"] == "completed"
        assert event.body["payload"] == {"session_id": "second"}
        assert hub.snapshot().session_id == "second"
    finally:
        client.close()
        thread.join(timeout=2)  # type: ignore[union-attr]
        hub.close()
    assert errors == []
