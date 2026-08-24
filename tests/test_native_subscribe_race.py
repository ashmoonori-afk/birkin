"""Events published while the bridge computes a subscription are not lost."""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import final

from birkin.native.capability import BootstrapSecretStore
from birkin.native.protocol import (
    NativeEnvelope,
    NativeProtocolError,
    encode_frame,
)
from birkin.native.server import NativeBridgeServer
from birkin.native.stream import BoundedEventBuffer
from birkin.native.transport import receive_frame
from birkin.workspace import CommandReceipt, SessionPreset, WorkspaceCommand
from birkin.workspace.records import WorkspaceEvent, WorkspaceSnapshot
from birkin.workspace.service import WorkspaceService
from tests.native_bridge_support import envelope, hello, local_peer_uid, serve


@final
class _SubscribeRaceSource:
    """Publish one canonical event while the bridge reads its replay batch."""

    def __init__(self, service: WorkspaceService) -> None:
        self._service = service
        self._pending: Callable[[], None] | None = None

    def publish_during_next_replay(self, action: Callable[[], None]) -> None:
        self._pending = action

    @property
    def supported_commands(self) -> frozenset[str]:
        return self._service.supported_commands

    @property
    def session_presets(self) -> tuple[SessionPreset, ...]:
        return self._service.session_presets

    def add_event_listener(
        self,
        listener: Callable[[WorkspaceEvent], None],
    ) -> Callable[[], None]:
        return self._service.add_event_listener(listener)

    def snapshot(self) -> WorkspaceSnapshot:
        return self._service.snapshot()

    def submit(self, command: WorkspaceCommand, *, actor_id: str) -> CommandReceipt:
        return self._service.submit(command, actor_id=actor_id)

    def events(self, *, after: int = 0) -> tuple[WorkspaceEvent, ...]:
        replayed = self._service.events(after=after)
        action, self._pending = self._pending, None
        if action is not None:
            action()
        return replayed


def _service(tmp_path: Path) -> WorkspaceService:
    service = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="session-1",
        handlers={},
    )

    def handle(payload: dict[str, object]) -> dict[str, object]:
        _ = service.emit("progress.updated", {"summary": str(payload["summary"])})
        return {"recorded": True}

    service.set_handlers({"chat.send": handle})
    return service


def _submit(service: WorkspaceService, *, command_id: str, summary: str) -> None:
    _ = service.submit(
        WorkspaceCommand.parse({
            "protocol_version": 1,
            "command_id": command_id,
            "expected_cursor": service.snapshot().cursor,
            "type": "chat.send",
            "payload": {"summary": summary},
            "client_context": {"surface": "test", "view_id": "race"},
        }),
        actor_id="test:race",
    )


def _subscribe(
    client: socket.socket,
    *,
    token: str,
    after_cursor: int,
) -> None:
    client.sendall(
        encode_frame(
            envelope(
                "subscribe",
                frame_id="subscribe-1",
                body={
                    "session_id": "session-1",
                    "after_cursor": after_cursor,
                    "known_instance_id": "instance-1",
                    "session_capability": token,
                    "surfaces": {},
                },
            )
        )
    )


def _read_event_cursors(
    client: socket.socket,
    *,
    until_cursor: int,
) -> list[int]:
    cursors: list[int] = []
    for _attempt in range(32):
        try:
            frame: NativeEnvelope = receive_frame(client)
        except NativeProtocolError as exc:
            raise AssertionError(
                f"cursor {until_cursor} was never delivered; saw {cursors}"
            ) from exc
        if frame.kind != "event":
            continue
        cursor = frame.body["cursor"]
        assert isinstance(cursor, int)
        cursors.append(cursor)
        if cursor >= until_cursor:
            return cursors
    raise AssertionError(f"cursor {until_cursor} was never delivered")


def test_event_published_during_subscribe_is_delivered_exactly_once(
    tmp_path: Path,
) -> None:
    """Given a reconnecting client, When Python publishes an event while the
    bridge is building the replay, Then the client receives that event exactly
    once and in cursor order."""
    service = _service(tmp_path)
    _submit(service, command_id="before-reconnect", summary="before reconnect")
    source = _SubscribeRaceSource(service)
    bridge = NativeBridgeServer(
        source,
        capabilities=BootstrapSecretStore(tmp_path / "native"),
        instance_id="instance-1",
        server_version="1.0.0",
    )
    raced = threading.Event()
    raced_cursor = 0

    def publish_raced_event() -> None:
        nonlocal raced_cursor
        _submit(service, command_id="raced", summary="raced")
        raced_cursor = service.snapshot().cursor
        raced.set()

    server_socket, client = socket.socketpair()
    client.settimeout(10)
    thread, errors = serve(
        bridge, server_socket, transport="uds", peer_uid=local_peer_uid()
    )
    try:
        client.sendall(encode_frame(hello(bootstrap_secret=None)))
        ready = receive_frame(client)
        capability = ready.body["capability"]
        assert isinstance(capability, dict)
        token = capability["token"]
        assert isinstance(token, str)
        source.publish_during_next_replay(publish_raced_event)

        _subscribe(client, token=token, after_cursor=0)

        assert raced.wait(10)
        cursors = _read_event_cursors(client, until_cursor=raced_cursor)
        assert cursors == sorted(cursors)
        assert len(cursors) == len(set(cursors))
        assert raced_cursor in cursors
    finally:
        client.close()
        server_socket.close()
        thread.join(timeout=5)
    assert errors == []


def test_buffered_cursor_hole_reports_desynchronization() -> None:
    """Given a buffer holding a non-contiguous cursor, When it is drained,
    Then a typed desynchronization notice replaces the events."""
    buffer = BoundedEventBuffer(capacity=8)
    buffer.resubscribe(after_cursor=4)
    _ = buffer.push({"cursor": 5, "type": "progress.updated"})
    _ = buffer.push({"cursor": 7, "type": "progress.updated"})

    drained = buffer.drain()

    assert [item.get("cursor") for item in drained] == [5]
    assert buffer.drain() == (
        {"kind": "stream.desynchronized", "body": {"resume_after": 5}},
    )


def test_buffered_events_before_the_delivered_cursor_are_dropped() -> None:
    """Given events already delivered by a replay, When the buffer learns the
    delivered cursor, Then it never re-delivers them."""
    buffer = BoundedEventBuffer(capacity=8)
    buffer.resubscribe(after_cursor=0)
    _ = buffer.push({"cursor": 1, "type": "progress.updated"})
    _ = buffer.push({"cursor": 2, "type": "progress.updated"})

    buffer.mark_delivered(cursor=1)

    assert [item.get("cursor") for item in buffer.drain()] == [2]
