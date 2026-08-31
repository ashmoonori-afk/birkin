from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from birkin.native.bridge_stream import NativeBridgeStream
from birkin.workspace import WorkspaceService
from tests.native_bridge_support import (
    CorrelatedFrameReader,
    handshake,
    local_peer_uid,
    serve,
)
from tests.native_control_support import (
    bridge as _bridge,
    send_command as _send,
    send_goodbye as _send_goodbye,
)
from tests.thread_deadline import ThreadDeadline

_TEST_DEADLINE_SECONDS: Final = 20.0


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

    bridge, source = _bridge(
        tmp_path,
        {
            "chat.send": chat_send,
            "chat.interrupt": interrupt,
            "chat.steer": steer,
            "chat.resume": resume,
        },
    )
    server_socket, client = socket.socketpair()
    client.settimeout(2)
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    token = handshake(client)
    client.settimeout(0)
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
        _send(
            client,
            token,
            "chat.send",
            "second-normal",
            source.snapshot().cursor,
            {"text": "no"},
        )
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
        assert [
            event.type for event in source.events() if event.type.startswith("turn.")
        ] == [
            "turn.interrupted",
            "turn.steered",
            "turn.resumed",
        ]
    finally:
        release_turn.set()
        replies.close()
        thread.join(timeout=3)
    assert (thread.is_alive(), errors) == (False, [])


def test_control_lanes_are_individually_bounded_and_join_disconnect_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deadline = ThreadDeadline.after(_TEST_DEADLINE_SECONDS)
    normal_entered = threading.Event()
    heartbeat_acknowledged = threading.Event()
    acknowledge_pong = NativeBridgeStream.acknowledge_pong

    def observe_pong(stream: NativeBridgeStream) -> None:
        acknowledge_pong(stream)
        heartbeat_acknowledged.set()

    monkeypatch.setattr(NativeBridgeStream, "acknowledge_pong", observe_pong)
    control_entered = {
        name: threading.Event() for name in ("interrupt", "steer", "resume")
    }
    control_completed = {name: threading.Event() for name in control_entered}
    release_normal = threading.Event()
    release_controls = threading.Event()
    cleaned = threading.Event()
    ordering: list[str] = []

    def normal(payload: dict[str, object]) -> dict[str, object]:
        normal_entered.set()
        deadline.wait_for(release_normal, "normal command release")
        ordering.append("normal")
        return {"reply": str(payload["text"])}

    def control(name: str) -> Callable[[dict[str, object]], dict[str, object]]:
        def run(_payload: dict[str, object]) -> dict[str, object]:
            control_entered[name].set()
            deadline.wait_for(release_controls, f"{name} release")
            ordering.append(name)
            control_completed[name].set()
            return {name: True}

        return run

    def cleanup() -> None:
        ordering.append("cleanup")
        cleaned.set()

    bridge, source = _bridge(
        tmp_path,
        {
            "chat.send": normal,
            "chat.interrupt": control("interrupt"),
            "chat.steer": control("steer"),
            "chat.resume": control("resume"),
        },
        cleanup=cleanup,
    )
    server_socket, client = socket.socketpair()
    client.settimeout(deadline.remaining)
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    token = handshake(client)
    replies = CorrelatedFrameReader(client, token)
    try:
        _send(client, token, "chat.send", "normal", 0, {"text": "work"})
        deadline.wait_for(normal_entered, "normal lane admission")
        deadline.wait_for(heartbeat_acknowledged, "heartbeat acknowledgement")
        for index, (name, event) in enumerate(control_entered.items(), start=1):
            payload = {"text": "direction"} if name == "steer" else {}
            _send(
                client, token, f"chat.{name}", name, source.snapshot().cursor, payload
            )
            deadline.wait_for(event, f"{name} lane admission")
            request_id = f"second-{name}"
            replies.expect(request_id)
            _send(
                client,
                token,
                f"chat.{name}",
                request_id,
                source.snapshot().cursor,
                payload,
            )
            refusal = replies.receive(request_id, timeout=deadline.remaining)
            assert refusal.body["code"] == "E_FLOW_VIOLATION"
            assert index <= 3

        workers = [
            worker
            for worker in threading.enumerate()
            if worker.name.startswith("birkin-native-command")
        ]
        assert len(workers) <= 4

        replies.expect_disconnect()
        _send_goodbye(client, token, "first-goodbye")
        deadline.join(thread, "first server disconnect")
        replies.close(timeout=deadline.remaining)
        assert not cleaned.is_set()

        second_server, second_client = socket.socketpair()
        second_client.settimeout(deadline.remaining)
        second_thread, second_errors = serve(
            bridge, second_server, transport="uds", peer_uid=local_peer_uid()
        )
        second_token = handshake(second_client)
        second_replies = CorrelatedFrameReader(second_client, second_token)
        second_replies.expect("after-disconnect")
        _send(
            second_client,
            second_token,
            "chat.send",
            "after-disconnect",
            source.snapshot().cursor,
            {"text": "no"},
        )
        refusal = second_replies.receive("after-disconnect", timeout=deadline.remaining)
        assert refusal.kind == "error"
        assert refusal.body["code"] == "E_FLOW_VIOLATION"
        second_replies.expect_disconnect()
        _send_goodbye(second_client, second_token, "second-goodbye")
        deadline.join(second_thread, "second server disconnect")
        second_replies.close(timeout=deadline.remaining)
        assert second_errors == []

        release_controls.set()
        for name, event in control_completed.items():
            deadline.wait_for(event, f"{name} completion")
        assert not cleaned.is_set()
        release_normal.set()
        deadline.wait_for(cleaned, "disconnect cleanup")
        assert ordering[-1] == "cleanup"
    finally:
        release_controls.set()
        release_normal.set()
        replies.close(timeout=deadline.remaining)
        deadline.join(thread, "first server shutdown")
    assert errors == []
