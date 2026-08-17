"""Authenticated native protocol bridge over a local connection."""

from __future__ import annotations

from typing import Protocol, final

from birkin.native.auth import NativeConnectionAuth
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
from birkin.workspace import CommandReceipt, WorkspaceCommand
from birkin.workspace.contracts import ProtocolError as WorkspaceProtocolError


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
        self._auth = NativeConnectionAuth(capabilities)
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
        issued_tokens: set[str] = set()
        with connection:
            try:
                hello = connection.receive()
                state.receive(hello)
                capability = self._auth.authenticate_hello(
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
                issued_tokens.add(capability.token)
                self._serve_messages(
                    connection,
                    state,
                    capability,
                    issued_tokens,
                )
            except NativeProtocolError as exc:
                if exc.code != "E_FRAME_INCOMPLETE":
                    connection.send(self._messages.error(exc))
            finally:
                for token in issued_tokens:
                    self._capabilities.revoke_session(token)

    def _serve_messages(
        self,
        connection: NativeConnection,
        state: NativeConnectionState,
        capability: SessionCapability,
        issued_tokens: set[str],
    ) -> None:
        active_token = capability.token
        while True:
            message = connection.receive()
            state.receive(message)
            self._auth.require_capability(message.body, active_token)
            renewed = self._capabilities.renew_if_due(active_token)
            if renewed is not None:
                active_token = renewed.token
                issued_tokens.add(active_token)
                renewal = self._messages.capability_renewed(renewed)
                state.send(renewal)
                connection.send(renewal)
            if message.kind == "goodbye":
                return
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
                self._send_projection(connection, state, message)
            elif message.kind == "command":
                try:
                    self._execute_command(connection, state, message)
                except WorkspaceProtocolError as exc:
                    self._send_workspace_error(
                        connection,
                        state,
                        message,
                        exc,
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

    def _send_workspace_error(
        self,
        connection: NativeConnection,
        state: NativeConnectionState,
        message: NativeEnvelope,
        error: WorkspaceProtocolError,
    ) -> None:
        response = self._messages.workspace_error(
            error,
            in_reply_to=message.id,
        )
        state.send(response)
        connection.send(response)
