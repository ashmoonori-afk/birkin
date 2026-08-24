"""Authenticated native protocol bridge over a local connection."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import final

from birkin.native.auth import NativeConnectionAuth
from birkin.native.bridge_commands import (
    NativeCommandCoordinator,
    NativeCommandExecution,
    NativeCommandExecutor,
)
from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.capability import BootstrapSecretStore, SessionCapability
from birkin.native.messages import NativeMessageFactory
from birkin.native.protocol import NativeProtocolError
from birkin.native.server_authority import (
    CommandAuthority as CommandAuthority,
    CommandRouter as _CommandRouter,
    ControlCommandAuthority as ControlCommandAuthority,
    SurfaceProjectionAuthority as SurfaceProjectionAuthority,
    WorkspaceAuthority as WorkspaceAuthority,
)
from birkin.native.server_projection import (
    NativeProjectionContext,
    NativeProjectionDelivery,
    ProjectionChannel,
)
from birkin.native.state import NativeConnectionState
from birkin.native.transport import NativeConnection

__all__ = [
    "CommandAuthority",
    "ControlCommandAuthority",
    "NativeBridgeServer",
    "SurfaceProjectionAuthority",
    "WorkspaceAuthority",
]


@dataclass(slots=True)
class _SessionCapabilityState:
    """Mutable capability lineage owned by one authenticated connection."""

    current: SessionCapability
    issued_tokens: set[str]


@final
class NativeBridgeServer:
    """Serve one authenticated thin-shell connection at a time."""

    def __init__(
        self,
        authority: WorkspaceAuthority,
        *,
        session_authority: WorkspaceAuthority | None = None,
        config_authority: CommandAuthority | None = None,
        capabilities: BootstrapSecretStore,
        instance_id: str,
        server_version: str,
        heartbeat_interval: float = 30.0,
        peer_timeout: float = 10.0,
        hello_timeout: float = 10.0,
        outbound_capacity: int = 512,
        on_disconnect: Callable[[], None] | None = None,
        surface_authority: SurfaceProjectionAuthority | None = None,
        voice_input_available: bool = False,
    ) -> None:
        if heartbeat_interval <= 0 or peer_timeout <= 0 or hello_timeout <= 0:
            raise ValueError("heartbeat intervals must be positive")
        projection_authority = session_authority or authority
        command_router = _CommandRouter(
            authority,
            session_authority,
            config_authority,
        )
        self._capabilities = capabilities
        self._auth = NativeConnectionAuth(
            capabilities,
            instance_id=instance_id,
        )
        self._instance_id = instance_id
        self._server_version = server_version
        self._messages = NativeMessageFactory(
            instance_id=instance_id,
            server_version=server_version,
            session_id=projection_authority.snapshot().session_id,
            command_types=command_router.supported_commands,
            session_presets=projection_authority.session_presets,
            surface_names=(
                surface_authority.surface_names
                if surface_authority is not None
                else ()
            ),
            voice_input_available=voice_input_available,
        )
        self._commands = NativeCommandCoordinator(
            NativeCommandExecutor(command_router, self._messages),
            on_disconnect,
        )
        self._projection = NativeProjectionDelivery(
            NativeProjectionContext(
                authority=projection_authority,
                surface_authority=surface_authority,
                instance_id=instance_id,
            ),
            self._messages,
        )
        self._listener_unsubscribe = projection_authority.add_event_listener(
            self._projection.publish
        )
        self._heartbeat_interval = heartbeat_interval
        self._peer_timeout = peer_timeout
        self._hello_timeout = hello_timeout
        self._outbound_capacity = outbound_capacity
        self._on_disconnect = on_disconnect

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
        command_execution: NativeCommandExecution | None = None
        with connection:
            try:
                # A silent pre-authentication client must not hold serial accept.
                connection.set_read_deadline(self._hello_timeout)
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
                connection.set_read_deadline(None)
                issued_tokens.add(capability.token)
                stream = NativeBridgeStream(
                    connection,
                    state,
                    self._messages,
                    heartbeat_interval=self._heartbeat_interval,
                    peer_timeout=self._peer_timeout,
                    capacity=self._outbound_capacity,
                )
                self._projection.attach(stream)
                stream.start()
                command_execution = NativeCommandExecution(
                    connection=connection,
                    state=state,
                    stream=stream,
                    scope=capability.scope,
                )
                self._serve_messages(
                    _SessionCapabilityState(capability, issued_tokens),
                    command_execution,
                )
            except NativeProtocolError as exc:
                if exc.code != "E_FRAME_INCOMPLETE":
                    connection.send(self._messages.error(exc))
            finally:
                if stream is not None:
                    self._projection.detach(stream)
                    stream.stop()
                for token in issued_tokens:
                    self._capabilities.revoke_session(token)
                if command_execution is not None:
                    self._commands.disconnect()
                elif self._on_disconnect is not None:
                    self._on_disconnect()

    def _serve_messages(
        self,
        capability_state: _SessionCapabilityState,
        execution: NativeCommandExecution,
    ) -> None:
        channel = ProjectionChannel(
            execution.connection,
            execution.state,
            execution.stream,
        )
        active_token = capability_state.current.token
        while True:
            message = execution.connection.receive()
            execution.state.receive(message)
            self._auth.require_capability(message.body, capability_state.current)
            renewed = self._capabilities.renew_if_due(active_token)
            if renewed is not None:
                capability_state.current = renewed
                active_token = renewed.token
                capability_state.issued_tokens.add(active_token)
                renewal = self._messages.capability_renewed(renewed)
                execution.state.send(renewal)
                execution.connection.send(renewal)
            if message.kind == "goodbye":
                return
            if message.kind == "pong":
                execution.stream.acknowledge_pong()
                continue
            if message.kind == "ping":
                pong_body: dict[str, object] = dict(message.body)
                _ = pong_body.pop("session_capability", None)
                response = self._messages.message(
                    "pong",
                    body=pong_body,
                    in_reply_to=message.id,
                )
                execution.state.send(response)
                execution.connection.send(response)
            elif message.kind == "subscribe":
                self._projection.send(channel, message)
            elif message.kind == "command" and not self._commands.submit(
                execution,
                message,
            ):
                refusal = self._messages.error(
                    NativeProtocolError(
                        "E_FLOW_VIOLATION",
                        "server already has an active command",
                    ),
                    in_reply_to=message.id,
                )
                execution.state.send(refusal)
                execution.connection.send(refusal)
