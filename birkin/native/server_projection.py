"""Live and reconnect projection delivery for native bridge connections."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import cast, final

from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.messages import NativeMessageFactory, body_integer, body_string
from birkin.native.product_surfaces import SURFACE_EVENT_SOURCES
from birkin.native.protocol import NativeEnvelope, NativeProtocolError
from birkin.native.server_authority import (
    SurfaceProjectionAuthority,
    WorkspaceAuthority,
)
from birkin.native.session import NativeProjectionSession
from birkin.native.state import NativeConnectionState
from birkin.native.transport import NativeConnection
from birkin.workspace.records import WorkspaceEvent


@dataclass(frozen=True, slots=True)
class NativeProjectionContext:
    """Authorities and identity shared by every connection projection."""

    authority: WorkspaceAuthority
    surface_authority: SurfaceProjectionAuthority | None
    instance_id: str


@dataclass(frozen=True, slots=True)
class ProjectionChannel:
    """Ordered connection surfaces used to deliver one subscription."""

    connection: NativeConnection
    state: NativeConnectionState
    stream: NativeBridgeStream


@final
class NativeProjectionDelivery:
    """Own active-stream publication and ordered subscription catch-up."""

    def __init__(
        self,
        context: NativeProjectionContext,
        messages: NativeMessageFactory,
    ) -> None:
        self._authority = context.authority
        self._surface_authority = context.surface_authority
        self._projection = NativeProjectionSession(
            context.authority,
            instance_id=context.instance_id,
        )
        self._messages = messages
        self._stream_lock = threading.Lock()
        self._active_stream: NativeBridgeStream | None = None

    def attach(self, stream: NativeBridgeStream) -> None:
        with self._stream_lock:
            self._active_stream = stream

    def detach(self, stream: NativeBridgeStream) -> None:
        with self._stream_lock:
            if self._active_stream is stream:
                self._active_stream = None

    def publish(self, event: WorkspaceEvent) -> None:
        """Publish canonical events without letting projections undo commits."""
        with self._stream_lock:
            stream = self._active_stream
        if stream is None:
            return
        stream.publish(event)
        surface = SURFACE_EVENT_SOURCES.get(event.type)
        if surface is None or self._surface_authority is None:
            return
        try:
            snapshot = self._surface_authority.live_snapshot(surface)
        except Exception:  # noqa: BLE001 - derived projection boundary
            # A failed projection does not advance its revision, so the next
            # successful payload remains the exact next frame the shell needs.
            return
        if snapshot is not None:
            stream.publish_surface(snapshot)

    def send(
        self,
        channel: ProjectionChannel,
        message: NativeEnvelope,
    ) -> None:
        """Deliver one ordered canonical and product-surface subscription."""
        session_id = body_string(message.body, "session_id")
        if session_id != self._authority.snapshot().session_id:
            raise NativeProtocolError(
                "E_SESSION_NOT_FOUND",
                "workspace session was not found",
            )
        after_cursor = body_integer(message.body, "after_cursor")
        known_instance = message.body["known_instance_id"]
        if known_instance is not None and not isinstance(known_instance, str):
            raise NativeProtocolError(
                "E_BODY",
                "known_instance_id must be a string or null",
            )
        channel.stream.suspend()
        try:
            channel.stream.activate(after_cursor=after_cursor)
            batch = self._projection.subscribe(
                after_cursor=after_cursor,
                known_instance_id=known_instance,
            )
            delivered_cursor = after_cursor
            if batch.snapshot is not None:
                body = dict(batch.snapshot)
                body["instance_id"] = batch.instance_id
                body["reset_reason"] = batch.reset_reason
                snapshot_cursor = body["cursor"]
                if isinstance(snapshot_cursor, int) and not isinstance(
                    snapshot_cursor, bool
                ):
                    delivered_cursor = max(delivered_cursor, snapshot_cursor)
                response = self._messages.message("snapshot", body=body)
                channel.state.send(response)
                channel.connection.send(response)
            if self._surface_authority is not None:
                requested = surface_revisions(message.body.get("surfaces"))
                try:
                    surface_snapshots = self._surface_authority.snapshots(requested)
                except ValueError as exc:
                    raise NativeProtocolError("E_BODY", str(exc)) from exc
                for surface_snapshot in surface_snapshots:
                    payload = dict(surface_snapshot.payload)
                    payload["_meta"] = {
                        "full_snapshot": surface_snapshot.full_snapshot,
                        "reset_reason": surface_snapshot.reset_reason,
                    }
                    response = self._messages.message(
                        "surface_snapshot",
                        body={
                            "surface": surface_snapshot.surface,
                            "revision": surface_snapshot.revision,
                            "payload": payload,
                        },
                    )
                    channel.state.send(response)
                    channel.connection.send(response)
            for event in batch.events:
                cursor = event.get("cursor")
                if isinstance(cursor, int) and not isinstance(cursor, bool):
                    delivered_cursor = max(delivered_cursor, cursor)
                response = self._messages.message("event", body=event)
                channel.state.send(response)
                channel.connection.send(response)
            channel.stream.mark_delivered(cursor=delivered_cursor)
        finally:
            channel.stream.resume()


def surface_revisions(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise NativeProtocolError("E_BODY", "surfaces must be an object")
    unknown = cast(dict[object, object], value)
    revisions: dict[str, int] = {}
    for key, revision in unknown.items():
        if not isinstance(key, str):
            raise NativeProtocolError("E_BODY", "surface names must be strings")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise NativeProtocolError(
                "E_BODY", "surface revisions must be non-negative integers"
            )
        revisions[key] = revision
    return revisions
