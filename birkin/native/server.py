"""Authenticated native protocol bridge over a local connection."""

from __future__ import annotations

from typing import Protocol, final

from birkin.native.capability import BootstrapSecretStore, SessionCapability
from birkin.native.messages import (
    NativeMessageFactory,
    body_integer,
    body_string,
)
from birkin.native.protocol import (
    NATIVE_PROTOCOL_VERSION,
    JSONValue,
    NativeEnvelope,
    NativeProtocolError,
)
from birkin.native.session import NativeProjectionSession, WorkspaceProjectionSource
from birkin.native.state import NativeConnectionState
from birkin.native.transport import NativeConnection
from birkin.workspace import CommandReceipt, WorkspaceCommand


class WorkspaceAuthority(WorkspaceProjectionSource, Protocol):
    def submit(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt: ...


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
        command_types: set[str],
    ) -> None:
        self._authority = authority
        self._capabilities = capabilities
        self._projection = NativeProjectionSession(
            authority,
            instance_id=instance_id,
        )
        self._instance_id = instance_id
        self._server_version = server_version
        self._command_types = frozenset(command_types)
        self._messages = NativeMessageFactory(
            instance_id=instance_id,
            server_version=server_version,
            command_types=self._command_types,
        )

    def serve_connection(
        self,
        connection: NativeConnection,
        *,
        transport: str,
    ) -> None:
        state = NativeConnectionState.server()
        with connection:
            try:
                hello = connection.receive()
                state.receive(hello)
                capability = self._authenticate_hello(
                    hello,
                    connection=connection,
                    transport=transport,
                )
                ready = self._messages.ready(
                    hello,
                    capability,
                    transport=transport,
                )
                state.send(ready)
                connection.send(ready)
                self._serve_messages(connection, state, capability)
            except NativeProtocolError as exc:
                if exc.code != "E_FRAME_INCOMPLETE":
                    connection.send(self._messages.error(exc))

    def _serve_messages(
        self,
        connection: NativeConnection,
        state: NativeConnectionState,
        capability: SessionCapability,
    ) -> None:
        active_token = capability.token
        while True:
            message = connection.receive()
            state.receive(message)
            if message.kind == "goodbye":
                return
            if message.kind == "ping":
                response = self._messages.message(
                    "pong",
                    body=dict(message.body),
                    in_reply_to=message.id,
                )
                state.send(response)
                connection.send(response)
            elif message.kind == "subscribe":
                self._require_capability(message.body, active_token)
                self._send_projection(connection, state, message)
            elif message.kind == "command":
                self._require_capability(message.body, active_token)
                self._execute_command(connection, state, message)

    def _authenticate_hello(
        self,
        hello: NativeEnvelope,
        *,
        connection: NativeConnection,
        transport: str,
    ) -> SessionCapability:
        versions = hello.body["supported_protocol_versions"]
        if (
            not isinstance(versions, list)
            or NATIVE_PROTOCOL_VERSION not in versions
        ):
            raise NativeProtocolError(
                "E_PROTOCOL_VERSION",
                "client and server share no native protocol version",
            )
        bootstrap = hello.body["bootstrap_secret"]
        if transport == "uds":
            if connection.peer_uid is None or bootstrap is not None:
                raise NativeProtocolError(
                    "E_PEER_UID_MISMATCH",
                    "Unix socket hello requires same-user peer credentials",
                )
            return self._capabilities.mint_session()
        if transport == "loopback" and isinstance(bootstrap, str):
            return self._capabilities.exchange(bootstrap)
        raise NativeProtocolError(
            "E_BOOTSTRAP_INVALID",
            "loopback hello requires a bootstrap secret",
        )

    def _send_projection(
        self,
        connection: NativeConnection,
        state: NativeConnectionState,
        message: NativeEnvelope,
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

    def _execute_command(
        self,
        connection: NativeConnection,
        state: NativeConnectionState,
        message: NativeEnvelope,
    ) -> None:
        command = WorkspaceCommand.parse(message.body.get("command"))
        if command.type not in self._command_types:
            raise NativeProtocolError(
                "E_UNSUPPORTED_COMMAND",
                "command is not advertised by this bridge",
            )
        receipt = self._authority.submit(
            command,
            actor_id=f"macos:{command.client_context.view_id}",
        )
        body = receipt.to_public_json()
        body["outcome"] = "duplicate" if receipt.duplicate else "accepted"
        response = self._messages.message(
            "receipt",
            body=body,
            in_reply_to=message.id,
        )
        state.send(response)
        connection.send(response)

    def _require_capability(
        self,
        body: dict[str, JSONValue],
        active_token: str,
    ) -> None:
        token = body.get("session_capability")
        if (
            not isinstance(token, str)
            or token != active_token
            or not self._capabilities.authenticate_session(token)
        ):
            raise NativeProtocolError(
                "E_CAPABILITY_INVALID",
                "native session capability is invalid",
            )
