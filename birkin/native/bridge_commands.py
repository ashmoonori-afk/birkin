"""Canonical workspace command execution for the native bridge."""

from __future__ import annotations

from typing import Protocol, final

from birkin.native.messages import NativeMessageFactory
from birkin.native.protocol import NativeEnvelope, NativeProtocolError
from birkin.native.state import NativeConnectionState
from birkin.native.transport import NativeConnection
from birkin.workspace import CommandReceipt, WorkspaceCommand
from birkin.workspace.contracts import ProtocolError as WorkspaceProtocolError


class WorkspaceCommandAuthority(Protocol):
    def submit(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt: ...


@final
class NativeCommandExecutor:
    def __init__(
        self,
        authority: WorkspaceCommandAuthority,
        messages: NativeMessageFactory,
    ) -> None:
        self._authority = authority
        self._messages = messages

    def execute(
        self,
        connection: NativeConnection,
        state: NativeConnectionState,
        message: NativeEnvelope,
    ) -> None:
        try:
            command = WorkspaceCommand.parse(message.body.get("command"))
            receipt = self._authority.submit(
                command,
                actor_id=f"macos:{command.client_context.view_id}",
            )
            body = receipt.to_public_json()
            if receipt.transient_result is not None and not receipt.duplicate:
                body["result"] = receipt.transient_result
            body["outcome"] = (
                "duplicate" if receipt.duplicate else "accepted"
            )
            response = self._messages.message(
                "receipt",
                body=body,
                in_reply_to=message.id,
            )
        except WorkspaceProtocolError as error:
            response = self._messages.workspace_error(
                error,
                in_reply_to=message.id,
            )
        except Exception as error:  # noqa: BLE001 - command boundary
            # A canonical handler failure is already journaled as
            # command.failed. It refuses this command; it must never take the
            # connection down with it.
            response = self._messages.error(
                NativeProtocolError("E_COMMAND_FAILED", str(error)),
                in_reply_to=message.id,
            )
        state.send(response)
        connection.send(response)
