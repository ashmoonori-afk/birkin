from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import (
    CorrelatedFrameReader,
    envelope,
    handshake,
    local_peer_uid,
    serve,
)


def _send(
    client: socket.socket,
    token: str,
    command_type: str,
    command_id: str,
    cursor: int,
    payload: Mapping[str, object],
    *,
    view_id: str = "main",
) -> None:
    client.sendall(encode_frame(envelope(
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
    )))


def _bridge(
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


def test_controls_execute_with_canonical_authority_during_active_normal_command(
    tmp_path: Path,
) -> None:
    turn_started = threading.Event()
    release_turn = threading.Event()
    interrupted = threading.Event()
    steered = threading.Event()
    resumed = threading.Event()
    source: WorkspaceService

    def chat_send(payload: dict[str, object]) -> dict[str, object]:
        turn_started.set()
        if not release_turn.wait(timeout=10):
            raise AssertionError("test did not release active turn")
        return {"reply": str(payload["text"])}

    def interrupt(_payload: dict[str, object]) -> dict[str, object]:
        assert turn_started.is_set()
        interrupted.set()
        _ = source.emit("turn.interrupted", {})
        return {"interrupted": True}

    def steer(payload: dict[str, object]) -> dict[str, object]:
        assert turn_started.is_set()
        steered.set()
        _ = source.emit("turn.steered", {"text": str(payload["text"])})
        return {"steered": True}

    def resume(_payload: dict[str, object]) -> dict[str, object]:
        assert interrupted.is_set()
        interrupted.clear()
        resumed.set()
        _ = source.emit("turn.resumed", {})
        return {"resumed": True}

    bridge, source = _bridge(tmp_path, {
        "chat.send": chat_send,
        "chat.interrupt": interrupt,
        "chat.steer": steer,
        "chat.resume": resume,
    })
    server_socket, client = socket.socketpair()
    client.settimeout(2)
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    token = handshake(client)
    replies = CorrelatedFrameReader(client, token)
    try:
        _send(client, token, "chat.send", "turn", 0, {"text": "work"})
        assert turn_started.wait(timeout=1)

        cursor = source.snapshot().cursor
        replies.expect("interrupt")
        _send(client, token, "chat.interrupt", "interrupt", cursor, {})
        assert replies.receive("interrupt").kind == "receipt"
        assert resumed.is_set() is False

        cursor = source.snapshot().cursor
        replies.expect("steer")
        _send(client, token, "chat.steer", "steer", cursor, {"text": "check tests"})
        assert replies.receive("steer").kind == "receipt"

        cursor = source.snapshot().cursor
        replies.expect("resume")
        _send(client, token, "chat.resume", "resume", cursor, {})
        assert replies.receive("resume").kind == "receipt"

        replies.expect("second-normal")
        _send(client, token, "chat.send", "second-normal", source.snapshot().cursor, {"text": "no"})
        refusal = replies.receive("second-normal")
        assert refusal.body["code"] == "E_FLOW_VIOLATION"

        replies.expect("wrong-scope")
        _send(
            client,
            token,
            "chat.interrupt",
            "wrong-scope",
            source.snapshot().cursor,
            {},
            view_id="other",
        )
        scope_error = replies.receive("wrong-scope")
        assert scope_error.body["code"] == "E_CAPABILITY_SCOPE"
        assert [event.type for event in source.events()].count("turn.interrupted") == 1

        assert steered.is_set()
        assert resumed.is_set()
        assert [event.type for event in source.events() if event.type.startswith("turn.")] == [
            "turn.interrupted",
            "turn.steered",
            "turn.resumed",
        ]
    finally:
        release_turn.set()
        replies.close()
        thread.join(timeout=3)
    assert errors == []


def test_control_lanes_are_individually_bounded_and_join_disconnect_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normal_entered = threading.Event()
    heartbeat_acknowledged = threading.Event()
    acknowledge_pong = NativeBridgeStream.acknowledge_pong

    def observe_pong(stream: NativeBridgeStream) -> None:
        acknowledge_pong(stream)
        heartbeat_acknowledged.set()

    monkeypatch.setattr(NativeBridgeStream, "acknowledge_pong", observe_pong)
    control_entered = {name: threading.Event() for name in ("interrupt", "steer", "resume")}
    control_completed = {name: threading.Event() for name in control_entered}
    release_normal = threading.Event()
    release_controls = threading.Event()
    cleaned = threading.Event()
    ordering: list[str] = []

    def normal(payload: dict[str, object]) -> dict[str, object]:
        normal_entered.set()
        if not release_normal.wait(timeout=10):
            raise AssertionError("test did not release normal command")
        ordering.append("normal")
        return {"reply": str(payload["text"])}

    def control(name: str) -> Callable[[dict[str, object]], dict[str, object]]:
        def run(_payload: dict[str, object]) -> dict[str, object]:
            control_entered[name].set()
            if not release_controls.wait(timeout=10):
                raise AssertionError(f"test did not release {name}")
            ordering.append(name)
            control_completed[name].set()
            return {name: True}

        return run

    def cleanup() -> None:
        ordering.append("cleanup")
        cleaned.set()

    bridge, source = _bridge(tmp_path, {
        "chat.send": normal,
        "chat.interrupt": control("interrupt"),
        "chat.steer": control("steer"),
        "chat.resume": control("resume"),
    }, cleanup=cleanup)
    server_socket, client = socket.socketpair()
    client.settimeout(2)
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    token = handshake(client)
    replies = CorrelatedFrameReader(client, token)
    try:
        _send(client, token, "chat.send", "normal", 0, {"text": "work"})
        assert normal_entered.wait(timeout=1)
        assert heartbeat_acknowledged.wait(timeout=1)
        for index, (name, event) in enumerate(control_entered.items(), start=1):
            payload = {"text": "direction"} if name == "steer" else {}
            _send(client, token, f"chat.{name}", name, source.snapshot().cursor, payload)
            assert event.wait(timeout=1)
            request_id = f"second-{name}"
            replies.expect(request_id)
            _send(client, token, f"chat.{name}", request_id, source.snapshot().cursor, payload)
            refusal = replies.receive(request_id)
            assert refusal.body["code"] == "E_FLOW_VIOLATION"
            assert index <= 3

        workers = [
            worker for worker in threading.enumerate()
            if worker.name.startswith("birkin-native-command")
        ]
        assert len(workers) <= 4

        replies.close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert not cleaned.is_set()

        second_server, second_client = socket.socketpair()
        second_client.settimeout(2)
        second_thread, second_errors = serve(
            bridge, second_server, transport="uds", peer_uid=local_peer_uid()
        )
        second_token = handshake(second_client)
        second_replies = CorrelatedFrameReader(second_client, second_token)
        second_replies.expect("after-disconnect")
        _send(second_client, second_token, "chat.send", "after-disconnect", source.snapshot().cursor, {"text": "no"})
        refusal = second_replies.receive("after-disconnect")
        assert refusal.kind == "error"
        assert refusal.body["code"] == "E_FLOW_VIOLATION"
        second_replies.close()
        second_thread.join(timeout=2)
        assert second_errors == []

        release_controls.set()
        for event in control_completed.values():
            assert event.wait(timeout=2)
        assert not cleaned.is_set()
        release_normal.set()
        assert cleaned.wait(timeout=2)
        assert ordering[-1] == "cleanup"
    finally:
        release_controls.set()
        release_normal.set()
        replies.close()
        thread.join(timeout=3)
    assert errors == []
