from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest

from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import (
    command_body,
    envelope,
    handshake,
    local_peer_uid,
    serve,
)


def test_blocked_command_flood_uses_one_worker_and_refuses_excess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    all_suspended = threading.Event()
    suspend_lock = threading.Lock()
    suspend_calls = 0
    original_suspend = NativeBridgeStream.suspend

    def counted_suspend(stream: NativeBridgeStream) -> None:
        nonlocal suspend_calls
        if threading.current_thread().name == "birkin-native-command":
            with suspend_lock:
                suspend_calls += 1
                if suspend_calls == 9:
                    all_suspended.set()
        original_suspend(stream)

    monkeypatch.setattr(NativeBridgeStream, "suspend", counted_suspend)

    def blocked_chat(payload: dict[str, object]) -> dict[str, object]:
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
        peer_timeout=0.5,
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
            frame_id="flood-command-0",
            body=command_body(
                token,
                command_id="flood-command-0",
                cursor=0,
                text="hold worker",
            ),
        )))
        assert entered.wait(timeout=1)

        for index in range(1, 9):
            client.sendall(encode_frame(envelope(
                "command",
                frame_id=f"flood-command-{index}",
                body=command_body(
                    token,
                    command_id=f"flood-command-{index}",
                    cursor=0,
                    text="flood",
                ),
            )))
        client.sendall(encode_frame(envelope(
            "ping",
            frame_id="flood-barrier-ping",
            body={
                "session_capability": token,
                "sent_at": "2026-08-21T00:00:00Z",
            },
        )))

        refusals = 0
        for heartbeat_index in range(32):
            frame = receive_frame(client)
            if frame.kind == "ping":
                client.sendall(encode_frame(envelope(
                    "pong",
                    frame_id=f"flood-heartbeat-pong-{heartbeat_index}",
                    in_reply_to=frame.id,
                    body={**frame.body, "session_capability": token},
                )))
                continue
            if frame.kind == "error":
                assert frame.body["code"] == "E_FLOW_VIOLATION"
                refusals += 1
                continue
            if frame.kind == "pong" and frame.in_reply_to == "flood-barrier-ping":
                break
        else:
            raise AssertionError("reader did not process the flood barrier")

        if refusals == 0:
            assert all_suspended.wait(timeout=1)
        assert (refusals, suspend_calls) == (7, 1)
    finally:
        release.set()
        client.close()
        thread.join(timeout=3)
    assert errors == []
