from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import NativeEnvelope, NativeProtocolError, encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceCommand, WorkspaceService
from tests import native_bridge_support
from tests.native_bridge_support import (
    command_body,
    envelope,
    handshake,
    local_peer_uid,
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
        peer_uid=local_peer_uid(),
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


def test_handshake_accepts_interleaved_ping_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge, _capabilities, _source = server_with_source(tmp_path)
    server_socket, client = socket.socketpair()
    thread, errors = serve(bridge, server_socket, transport="uds", peer_uid=local_peer_uid())
    responses = iter(
        (None, envelope("ping", frame_id="heartbeat-1", body={}), None)
    )

    def receive_with_interleaved_ping(connection: socket.socket) -> NativeEnvelope:
        response = next(responses)
        return receive_frame(connection) if response is None else response

    monkeypatch.setattr(native_bridge_support, "receive_frame", receive_with_interleaved_ping)
    try:
        assert handshake(client)
    finally:
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_blocked_command_keeps_heartbeat_live_until_ordered_receipt(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked_chat(payload: dict[str, object]) -> dict[str, object]:
        entered.set()
        if not release.wait(timeout=30):
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
        heartbeat_interval=0.005,
        peer_timeout=0.5,
    )
    server_socket, client = socket.socketpair()
    client.settimeout(1)
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
            frame_id="blocked-command-frame",
            body=command_body(
                token,
                command_id="blocked-command",
                cursor=0,
                text="wait for release",
            ),
        )))
        assert entered.wait(timeout=1)

        for index in range(3):
            ping = receive_frame(client)
            assert ping.kind == "ping", ping.body
            pong_body: dict[str, object] = {
                key: value for key, value in ping.body.items()
            }
            pong_body["session_capability"] = token
            client.sendall(encode_frame(envelope(
                "pong",
                frame_id=f"blocked-command-pong-{index}",
                in_reply_to=ping.id,
                body=pong_body,
            )))
        release.set()

        command_frames: list[NativeEnvelope] = []
        deadline = time.monotonic() + 5
        final_pong_index = 0
        while time.monotonic() < deadline:
            client.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                frame = receive_frame(client)
            except TimeoutError as error:
                raise AssertionError(
                    "command completion was not delivered"
                ) from error
            if frame.kind == "ping":
                pong_body = {
                    key: value for key, value in frame.body.items()
                }
                pong_body["session_capability"] = token
                client.sendall(encode_frame(envelope(
                    "pong",
                    frame_id=f"blocked-command-final-pong-{final_pong_index}",
                    in_reply_to=frame.id,
                    body=pong_body,
                )))
                final_pong_index += 1
                continue
            command_frames.append(frame)
            if (
                frame.kind == "event"
                and frame.body.get("type") == "command.completed"
            ):
                break
        else:
            raise AssertionError("command completion was not delivered")

        assert command_frames[0].kind == "receipt"
        assert command_frames[0].in_reply_to == "blocked-command-frame"
        assert command_frames[-1].body["command_id"] == "blocked-command"
    finally:
        release.set()
        client.close()
        thread.join(timeout=2)
    assert errors == []


def test_peer_loss_terminates_connection_while_command_is_blocked(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked_chat(payload: dict[str, object]) -> dict[str, object]:
        entered.set()
        if not release.wait(timeout=2):
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
        assert entered.wait(timeout=1)

        client.close()
        thread.join(timeout=3)

        assert not thread.is_alive()
    finally:
        release.set()
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
        peer_uid=local_peer_uid(),
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
