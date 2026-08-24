from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import NativeEnvelope, encode_frame
from birkin.native.server import NativeBridgeServer
from birkin.native.transport import receive_frame
from birkin.workspace import WorkspaceService
from birkin.workspace.records import WorkspaceEvent
from tests.native_bridge_support import (
    command_body,
    envelope,
    handshake,
    local_peer_uid,
    serve,
)


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


def test_repeated_blocked_disconnects_keep_command_and_unsubscribe_threads_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release_commands = threading.Event()
    release_unsubscribes = threading.Event()
    first_completed = threading.Event()
    command_started = threading.Event()
    original_suspend = NativeBridgeStream.suspend

    def signal_command_start(stream: NativeBridgeStream) -> None:
        command_started.set()
        original_suspend(stream)

    monkeypatch.setattr(NativeBridgeStream, "suspend", signal_command_start)

    def blocked_chat(payload: dict[str, object]) -> dict[str, object]:
        entered.set()
        if not release_commands.wait(timeout=10):
            raise AssertionError("test did not release blocked command")
        first_completed.set()
        return {"reply": str(payload["text"])}

    def blocking_listener_registration(
        _source: WorkspaceService,
        _listener: Callable[[WorkspaceEvent], None],
    ) -> Callable[[], None]:
        def unsubscribe() -> None:
            if not release_unsubscribes.wait(timeout=10):
                raise AssertionError("test did not release unsubscribe")

        return unsubscribe

    monkeypatch.setattr(
        WorkspaceService,
        "add_event_listener",
        blocking_listener_registration,
    )
    source = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={"chat.send": blocked_chat},
    )
    projection = WorkspaceService(
        root=tmp_path / "projection",
        session_id="session-1",
        handlers={},
    )
    bridge = NativeBridgeServer(
        source,
        session_authority=projection,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
        heartbeat_interval=0.05,
        peer_timeout=0.5,
    )
    command_threads = -1
    unsubscribe_threads = -1
    all_errors: list[BaseException] = []
    try:
        for cycle in range(3):
            server_socket, client = socket.socketpair()
            client.settimeout(2)
            thread, errors = serve(
                bridge,
                server_socket,
                transport="uds",
                peer_uid=local_peer_uid(),
            )
            token = handshake(client)
            if cycle > 0:
                client.sendall(encode_frame(envelope(
                    "ping",
                    frame_id=f"queued-heartbeat-{cycle}",
                    body={
                        "session_capability": token,
                        "sent_at": "2026-08-21T00:00:00Z",
                    },
                )))
            _send_command(client, token, command_id=f"blocked-{cycle}")
            if cycle == 0:
                assert command_started.wait(timeout=1)
                assert entered.wait(timeout=1)
            else:
                frames = _barrier(client, token, f"barrier-{cycle}")
                refusals = [
                    frame
                    for frame in frames
                    if frame.kind == "error"
                    and frame.in_reply_to == f"blocked-{cycle}"
                ]
                assert [(frame.in_reply_to, frame.body["code"]) for frame in refusals] == [
                    (f"blocked-{cycle}", "E_FLOW_VIOLATION")
                ]
            client.close()
            thread.join(timeout=2)
            assert not thread.is_alive()
            all_errors.extend(errors)

        command_threads = sum(
            thread.name == "birkin-native-command"
            for thread in threading.enumerate()
        )
        unsubscribe_threads = sum(
            thread.name == "birkin-native-unsubscribe"
            for thread in threading.enumerate()
        )
        assert command_threads <= 1
        assert unsubscribe_threads == 0
    finally:
        release_commands.set()
        release_unsubscribes.set()
        if command_threads > 0:
            assert first_completed.wait(timeout=2)
    assert all_errors == []


def test_disconnect_cleanup_runs_after_blocked_command_mutation(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    mutated = threading.Event()
    cleaned = threading.Event()
    resources: list[str] = []
    ordering: list[str] = []

    def blocked_chat(payload: dict[str, object]) -> dict[str, object]:
        entered.set()
        if not release.wait(timeout=10):
            raise AssertionError("test did not release blocked command")
        resources.append("late-resource")
        ordering.append("mutation")
        mutated.set()
        return {"reply": str(payload["text"])}

    def cleanup() -> None:
        resources.clear()
        ordering.append("cleanup")
        cleaned.set()

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
    token = handshake(client)
    try:
        _send_command(client, token, command_id="late-mutation")
        assert entered.wait(timeout=1)
        client.close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert not cleaned.is_set()

        second_server, second_client = socket.socketpair()
        second_client.settimeout(2)
        second_thread, second_errors = serve(
            bridge,
            second_server,
            transport="uds",
            peer_uid=local_peer_uid(),
        )
        second_token = handshake(second_client)
        _send_command(second_client, second_token, command_id="refused-late")
        refusal = receive_frame(second_client)
        assert refusal.body["code"] == "E_FLOW_VIOLATION"
        second_client.close()
        second_thread.join(timeout=2)
        assert second_errors == []
        assert not cleaned.is_set()

        release.set()
        assert mutated.wait(timeout=2)
        assert cleaned.wait(timeout=2)
        assert ordering == ["mutation", "cleanup"]
        assert resources == []
    finally:
        release.set()
        client.close()
        thread.join(timeout=2)
    assert errors == []
