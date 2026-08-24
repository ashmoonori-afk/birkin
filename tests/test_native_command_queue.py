from __future__ import annotations

import socket
import threading
from pathlib import Path
from queue import Queue

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import NativeEnvelope, NativeProtocolError, encode_frame
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
    limits = ready.body["limits"]
    assert isinstance(limits, dict)
    capacity = limits["max_inflight_commands"]
    assert isinstance(capacity, int)
    admitted_command_ids = frozenset(
        f"admitted-{index}" for index in range(capacity)
    )
    received_frames: Queue[NativeEnvelope] = Queue()
    refusals: Queue[NativeEnvelope] = Queue()
    reader_errors: list[BaseException] = []
    reader_started = threading.Event()
    reader_stop = threading.Event()
    heartbeat_acknowledged = threading.Event()
    refusal_received = threading.Event()
    barrier_received = threading.Event()
    admitted_receipts_received = threading.Event()
    completed_command_ids: set[str] = set()
    completed_command_ids_lock = threading.Lock()

    def read_client() -> None:
        reader_started.set()
        try:
            while not reader_stop.is_set():
                frame = receive_frame(client)
                if frame.kind == "ping":
                    client.sendall(encode_frame(envelope(
                        "pong",
                        frame_id=f"heartbeat-pong-{frame.id}",
                        in_reply_to=frame.id,
                        body={**frame.body, "session_capability": token},
                    )))
                    heartbeat_acknowledged.set()
                    continue
                received_frames.put(frame)
                if (
                    frame.kind == "error"
                    and frame.in_reply_to == "beyond-capacity"
                ):
                    refusals.put(frame)
                    refusal_received.set()
                if (
                    frame.kind == "pong"
                    and frame.in_reply_to == "capacity-barrier"
                ):
                    barrier_received.set()
                if (
                    frame.kind == "receipt"
                    and frame.in_reply_to in admitted_command_ids
                ):
                    assert frame.in_reply_to is not None
                    with completed_command_ids_lock:
                        completed_command_ids.add(frame.in_reply_to)
                        complete = completed_command_ids >= admitted_command_ids
                    if complete:
                        admitted_receipts_received.set()
                        return
        except (NativeProtocolError, OSError) as exc:
            reader_errors.append(exc)

    reader_thread = threading.Thread(target=read_client)
    reader_thread.start()
    try:
        assert reader_started.wait(timeout=1)
        for command_id in admitted_command_ids:
            _send_command(client, token, command_id=command_id)
        assert entered.wait(timeout=1)
        assert heartbeat_acknowledged.wait(timeout=1)

        _send_command(client, token, command_id="beyond-capacity")
        assert refusal_received.wait(timeout=1)
        client.sendall(encode_frame(envelope(
            "ping",
            frame_id="capacity-barrier",
            body={
                "session_capability": token,
                "sent_at": "2026-08-21T00:00:00Z",
            },
        )))
        assert barrier_received.wait(timeout=1)

        refusal = refusals.get_nowait()
        assert (refusal.in_reply_to, refusal.body["code"]) == (
            "beyond-capacity",
            "E_FLOW_VIOLATION",
        )
    finally:
        release.set()
        admitted_receipts_complete = admitted_receipts_received.wait(timeout=2)
        reader_stop.set()
        try:
            client.shutdown(socket.SHUT_RDWR)
        finally:
            client.close()
            reader_thread.join(timeout=2)
            thread.join(timeout=3)
        assert admitted_receipts_complete
        assert not reader_thread.is_alive()
        assert not thread.is_alive()
    assert received_frames.qsize() >= 3
    assert reader_errors == []
    assert errors == []
