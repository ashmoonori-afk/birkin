from __future__ import annotations

import socket
import threading
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import NativeEnvelope, encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import (
    command_body,
    envelope,
    hello,
    local_peer_uid,
    serve,
)


def _connect(
    bridge: NativeBridgeServer,
) -> tuple[socket.socket, str, NativeEnvelope, threading.Thread, list[BaseException]]:
    server_socket, client = socket.socketpair()
    client.settimeout(2)
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
    client.sendall(encode_frame(envelope(
        "subscribe",
        frame_id="subscribe-1",
        body={
            "session_id": "session-1",
            "after_cursor": 0,
            "known_instance_id": None,
            "session_capability": token,
            "surfaces": {},
        },
    )))
    assert receive_frame(client).kind == "snapshot"
    return client, token, ready, thread, errors


def _send_command(
    client: socket.socket,
    token: str,
    *,
    command_id: str,
) -> None:
    client.sendall(encode_frame(envelope(
        "command",
        frame_id=command_id,
        body=command_body(
            token,
            command_id=command_id,
            cursor=0,
            text=command_id,
        ),
    )))


def _barrier(client: socket.socket, token: str, frame_id: str) -> list[NativeEnvelope]:
    client.sendall(encode_frame(envelope(
        "ping",
        frame_id=frame_id,
        body={
            "session_capability": token,
            "sent_at": "2026-08-21T00:00:00Z",
        },
    )))
    received: list[NativeEnvelope] = []
    for _index in range(32):
        frame = receive_frame(client)
        if frame.kind == "ping":
            client.sendall(encode_frame(envelope(
                "pong",
                frame_id=f"heartbeat-pong-{frame.id}",
                in_reply_to=frame.id,
                body={**frame.body, "session_capability": token},
            )))
            continue
        if frame.kind == "pong" and frame.in_reply_to == frame_id:
            return received
        received.append(frame)
    raise AssertionError("reader did not process the barrier")


def test_advertised_inflight_capacity_is_admitted_before_correlated_refusal(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()

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
    client, token, ready, thread, errors = _connect(bridge)
    try:
        limits = ready.body["limits"]
        assert isinstance(limits, dict)
        capacity = limits["max_inflight_commands"]
        assert isinstance(capacity, int)

        for index in range(capacity):
            _send_command(client, token, command_id=f"admitted-{index}")
        assert entered.wait(timeout=1)
        _send_command(client, token, command_id="beyond-capacity")
        frames = _barrier(client, token, "capacity-barrier")
        refusals = [frame for frame in frames if frame.kind == "error"]

        assert [(frame.in_reply_to, frame.body["code"]) for frame in refusals] == [
            ("beyond-capacity", "E_FLOW_VIOLATION")
        ]
    finally:
        release.set()
        client.close()
        thread.join(timeout=3)
    assert errors == []
