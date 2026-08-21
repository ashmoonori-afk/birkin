"""Per-connection live event writer and heartbeat supervision."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import cast, final

from birkin.native.messages import NativeMessageFactory
from birkin.native.product_surfaces import SurfaceSnapshot
from birkin.native.projection import public_workspace_event
from birkin.native.state import NativeConnectionState
from birkin.native.stream import NativeEventQueue
from birkin.native.transport import NativeConnection
from birkin.workspace.records import WorkspaceEvent


@final
class NativeBridgeStream:
    def __init__(
        self,
        connection: NativeConnection,
        state: NativeConnectionState,
        messages: NativeMessageFactory,
        *,
        heartbeat_interval: float,
        peer_timeout: float,
        capacity: int,
    ) -> None:
        self._connection = connection
        self._state = state
        self._messages = messages
        self._heartbeat_interval = heartbeat_interval
        self._peer_timeout = peer_timeout
        self._queue = NativeEventQueue(capacity=capacity)
        self._active = threading.Event()
        self._send_gate = threading.RLock()
        self._delivery_suspended = threading.Event()
        self._stopped = threading.Event()
        self._pong = threading.Event()
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="birkin-native-writer",
            daemon=True,
        )

    @property
    def failure(self) -> BaseException | None:
        return self._failure

    def start(self) -> None:
        self._thread.start()

    def activate(self, *, after_cursor: int) -> None:
        self._queue.resubscribe(after_cursor=after_cursor)
        self._active.set()

    def mark_delivered(self, *, cursor: int) -> None:
        self._queue.mark_delivered(cursor=cursor)

    def publish(self, event: WorkspaceEvent) -> None:
        if self._active.is_set():
            self._queue.publish(public_workspace_event(event))

    def publish_surface(self, snapshot: SurfaceSnapshot) -> None:
        """Queue one revisioned product-surface frame behind its event."""
        if self._active.is_set():
            self._queue.publish({
                "kind": "surface_event",
                "body": {
                    "surface": snapshot.surface,
                    "revision": snapshot.revision,
                    "payload": snapshot.payload,
                },
            })

    def acknowledge_pong(self) -> None:
        self._pong.set()

    def suspend(self) -> None:
        """Hold queued delivery until the caller has written its own frames.

        Acquiring the gate also waits out any send already in flight, so a
        drained batch can never overtake a snapshot or a command receipt.
        Heartbeats remain live while synchronous command work owns the gate.
        """
        self._delivery_suspended.set()
        _ = self._send_gate.acquire()

    def resume(self) -> None:
        self._delivery_suspended.clear()
        self._send_gate.release()

    def stop(self) -> None:
        self._stopped.set()
        self._pong.set()
        self._queue.close()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            while not self._stopped.is_set():
                self._queue.wait_for_pending(timeout=self._heartbeat_interval)
                if self._stopped.is_set():
                    return
                acquired = self._send_gate.acquire(
                    timeout=self._heartbeat_interval
                )
                if not acquired:
                    if self._delivery_suspended.is_set():
                        self._send_heartbeat()
                    continue
                try:
                    if self._stopped.is_set():
                        return
                    events = self._queue.drain()
                    if events:
                        self._send_events(events)
                        continue
                    self._send_heartbeat()
                finally:
                    self._send_gate.release()
                if not self._pong.wait(self._peer_timeout):
                    if self._delivery_suspended.is_set():
                        continue
                    self._connection.interrupt()
                    return
        except BaseException as exc:
            self._failure = exc
            self._connection.interrupt()

    def _send_heartbeat(self) -> None:
        self._pong.clear()
        ping = self._messages.message(
            "ping",
            body={
                "sent_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._state.send(ping)
        self._connection.send(ping)

    def _send_events(
        self,
        events: tuple[dict[str, object], ...],
    ) -> None:
        for item in events:
            marker = item.get("kind")
            if isinstance(marker, str):
                raw_body = item.get("body")
                body = (
                    cast(dict[str, object], raw_body)
                    if isinstance(raw_body, dict)
                    else {}
                )
                envelope = self._messages.message(marker, body=body)
            else:
                envelope = self._messages.message("event", body=item)
            self._state.send(envelope)
            self._connection.send(envelope)
