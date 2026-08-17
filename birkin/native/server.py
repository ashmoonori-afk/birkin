"""Authenticated native protocol bridge over a local connection."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Protocol, final

from birkin.native.auth import NativeConnectionAuth
from birkin.native.bridge_commands import (
    NativeCommandExecutor,
    WorkspaceCommandAuthority,
)
from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.capability import BootstrapSecretStore, SessionCapability
from birkin.native.messages import (
    NativeMessageFactory,
    body_integer,
    body_string,
)
from birkin.native.protocol import (
    NativeEnvelope,
    NativeProtocolError,
)
from birkin.native.session import NativeProjectionSession, WorkspaceProjectionSource
from birkin.native.state import NativeConnectionState
from birkin.native.transport import NativeConnection
from birkin.workspace.records import WorkspaceEvent


class WorkspaceAuthority(
    WorkspaceProjectionSource,
    WorkspaceCommandAuthority,
    Protocol,
):
    @property
    def supported_commands(self) -> frozenset[str]: ...

    def add_event_listener(
        self,
        listener: Callable[[WorkspaceEvent], None],
    ) -> Callable[[], None]: ...

@final
class NativeBridgeServer:
    """Serve one authenticated thin-shell connection at a time."""

    def __init__(
        self,
        authority: WorkspaceAuthority,
        *,
        capabilities: BootstrapSecretStore,
        instance_id: str,
        server_version: str,
        heartbeat_interval: float = 30.0,
        peer_timeout: float = 10.0,
        outbound_capacity: int = 512,
    ) -> None:
        if heartbeat_interval <= 0 or peer_timeout <= 0:
            raise ValueError("heartbeat intervals must be positive")
        self._authority = authority
        self._capabilities = capabilities
        self._auth = NativeConnectionAuth(
            capabilities,
            instance_id=instance_id,
        )
        self._projection = NativeProjectionSession(
            authority,
            instance_id=instance_id,
        )
        self._instance_id = instance_id
        self._server_version = server_version
        self._messages = NativeMessageFactory(
            instance_id=instance_id,
            server_version=server_version,
            command_types=authority.supported_commands,
        )
        self._commands = NativeCommandExecutor(authority, self._messages)
        self._heartbeat_interval = heartbeat_interval
        self._peer_timeout = peer_timeout
        self._outbound_capacity = outbound_capacity

    def serve_connection(
        self,
        connection: NativeConnection,
        *,
        transport: str,
    ) -> None:
        state = NativeConnectionState.server()
        issued_tokens: set[str] = set()
        connection_id = secrets.token_urlsafe(16)
        stream: NativeBridgeStream | None = None
        unsubscribe: Callable[[], None] | None = None
        with connection:
            try:
                hello = connection.receive()
                state.receive(hello)
                capability = self._auth.authenticate_hello(
                    hello,
                    connection=connection,
                    transport=transport,
                    connection_id=connection_id,
                )
                ready = self._messages.ready(
                    hello,
                    capability,
                    transport=transport,
                )
                state.send(ready)
                connection.send(ready)
                issued_tokens.add(capability.token)
                stream = NativeBridgeStream(
                    connection,
                    state,
                    self._messages,
                    heartbeat_interval=self._heartbeat_interval,
                    peer_timeout=self._peer_timeout,
                    capacity=self._outbound_capacity,
                )
                unsubscribe = self._authority.add_event_listener(
                    stream.publish,
                )
                stream.start()
                self._serve_messages(
                    connection,
                    state,
                    capability,
                    issued_tokens,
                    stream,
                )
            except NativeProtocolError as exc:
                if exc.code != "E_FRAME_INCOMPLETE":
                    connection.send(self._messages.error(exc))
            finally:
                if unsubscribe is not None:
                    unsubscribe()
                if stream is not None:
                    stream.stop()
                for token in issued_tokens:
                    self._capabilities.revoke_session(token)

    def _serve_messages(
        self,
        connection: NativeConnection,
        state: NativeConnectionState,
        capability: SessionCapability,
        issued_tokens: set[str],
        stream: NativeBridgeStream,
    ) -> None:
        active_token = capability.token
        while True:
            message = connection.receive()
            state.receive(message)
            self._auth.require_capability(message.body, capability)
            renewed = self._capabilities.renew_if_due(active_token)
            if renewed is not None:
                capability = renewed
                active_token = renewed.token
                issued_tokens.add(active_token)
                renewal = self._messages.capability_renewed(renewed)
                state.send(renewal)
                connection.send(renewal)
            if message.kind == "goodbye":
                return
            if message.kind == "pong":
                stream.acknowledge_pong()
                continue
            if message.kind == "ping":
                pong_body: dict[str, object] = dict(message.body)
                _ = pong_body.pop("session_capability", None)
                response = self._messages.message(
                    "pong",
                    body=pong_body,
                    in_reply_to=message.id,
                )
                state.send(response)
                connection.send(response)
            elif message.kind == "subscribe":
                self._send_projection(
                    connection,
                    state,
                    message,
                    stream,
                )
            elif message.kind == "command":
                stream.suspend()
                try:
                    self._commands.execute(
                        connection,
                        state,
                        message,
                    )
                finally:
                    stream.resume()

    def _send_projection(
        self,
        connection: NativeConnection,
        state: NativeConnectionState,
        message: NativeEnvelope,
        stream: NativeBridgeStream,
    ) -> None:
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
        batch = self._projection.subscribe(
            after_cursor=after_cursor,
            known_instance_id=known_instance,
        )
        if batch.snapshot is not None:
            body = dict(batch.snapshot)
            body["instance_id"] = batch.instance_id
            body["reset_reason"] = batch.reset_reason
            response = self._messages.message("snapshot", body=body)
            state.send(response)
            connection.send(response)
        for event in batch.events:
            response = self._messages.message("event", body=event)
            state.send(response)
            connection.send(response)
        stream.activate(after_cursor=after_cursor)
