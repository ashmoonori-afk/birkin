"""Canonical workspace command execution for the native bridge."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, final

from birkin.native.bridge_stream import NativeBridgeStream
from birkin.native.capability import CapabilityScope
from birkin.native.messages import NativeMessageFactory
from birkin.native.protocol import NativeEnvelope, NativeProtocolError
from birkin.native.state import NativeConnectionState
from birkin.native.transport import NativeConnection
from birkin.workspace import CommandReceipt, WorkspaceCommand
from birkin.workspace.contracts import ProtocolError as WorkspaceProtocolError


@final
@dataclass(frozen=True, slots=True)
class NativeCommandExecution:
    """Resources owned by one admitted command connection."""

    connection: NativeConnection
    state: NativeConnectionState
    stream: NativeBridgeStream
    scope: CapabilityScope


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
        scope: CapabilityScope,
    ) -> None:
        try:
            command = WorkspaceCommand.parse(message.body.get("command"))
            if (
                command.client_context.surface != scope.surface
                or command.client_context.view_id != scope.view_id
            ):
                raise NativeProtocolError(
                    "E_CAPABILITY_SCOPE",
                    "command context is outside the connection capability scope",
                )
            receipt = self._authority.submit(
                command,
                actor_id=f"{scope.surface}:{scope.view_id}",
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
        except NativeProtocolError as error:
            response = self._messages.error(
                error,
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


@final
class NativeCommandCoordinator:
    """Admit at most one server-wide command and fence disconnect cleanup."""

    def __init__(
        self,
        executor: NativeCommandExecutor,
        cleanup: Callable[[], None] | None,
    ) -> None:
        self._executor = executor
        self._cleanup = cleanup
        self._lock = threading.Lock()
        self._active: NativeCommandExecution | None = None
        self._cleanup_pending = False

    def submit(
        self,
        execution: NativeCommandExecution,
        message: NativeEnvelope,
    ) -> bool:
        with self._lock:
            if self._active is not None:
                return False
            self._active = execution
        threading.Thread(
            target=self._run,
            args=(execution, message),
            name="birkin-native-command",
            daemon=True,
        ).start()
        return True

    def disconnect(self) -> None:
        with self._lock:
            if self._active is not None:
                self._cleanup_pending = True
            elif self._cleanup is not None:
                self._cleanup()

    def _run(
        self,
        execution: NativeCommandExecution,
        message: NativeEnvelope,
    ) -> None:
        execution.stream.suspend()
        try:
            self._executor.execute(
                execution.connection,
                execution.state,
                message,
                execution.scope,
            )
        except (NativeProtocolError, OSError):
            execution.connection.interrupt()
        finally:
            execution.stream.resume()
            with self._lock:
                if self._active is execution:
                    self._active = None
                if self._cleanup_pending:
                    self._cleanup_pending = False
                    if self._cleanup is not None:
                        self._cleanup()
