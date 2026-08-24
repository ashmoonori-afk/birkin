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
from birkin.workspace.contracts import (
    CONTROL_COMMAND_TYPES,
    ProtocolError as WorkspaceProtocolError,
)

_NORMAL_LANE = "normal"


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
        _connection: NativeConnection,
        _state: NativeConnectionState,
        message: NativeEnvelope,
        scope: CapabilityScope,
    ) -> NativeEnvelope | None:
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
        return response


@final
class NativeCommandCoordinator:
    """Admit one normal mutation plus one worker per explicit turn control."""

    def __init__(
        self,
        executor: NativeCommandExecutor,
        cleanup: Callable[[], None] | None,
    ) -> None:
        self._executor = executor
        self._cleanup = cleanup
        self._lock = threading.Lock()
        self._active: dict[str, NativeCommandExecution] = {}
        self._cleanup_pending = False

    def submit(
        self,
        execution: NativeCommandExecution,
        message: NativeEnvelope,
    ) -> bool:
        lane = self._lane(message)
        with self._lock:
            if self._cleanup_pending or lane in self._active:
                return False
            self._active[lane] = execution
        try:
            threading.Thread(
                target=self._run,
                args=(execution, message, lane),
                name=(
                    "birkin-native-command"
                    if lane == _NORMAL_LANE
                    else f"birkin-native-command-{lane.replace('.', '-')}"
                ),
                daemon=True,
            ).start()
        except BaseException:
            self._finish(execution, lane)
            raise
        return True

    def disconnect(self) -> None:
        with self._lock:
            if self._active:
                self._cleanup_pending = True
            elif self._cleanup is not None:
                self._cleanup()

    @staticmethod
    def _lane(message: NativeEnvelope) -> str:
        try:
            command = WorkspaceCommand.parse(message.body.get("command"))
        except WorkspaceProtocolError:
            return _NORMAL_LANE
        return command.type if command.type in CONTROL_COMMAND_TYPES else _NORMAL_LANE

    def _run(
        self,
        execution: NativeCommandExecution,
        message: NativeEnvelope,
        lane: str,
    ) -> None:
        suspended = False
        try:
            if lane == _NORMAL_LANE:
                execution.stream.suspend()
                suspended = True
            response = self._executor.execute(
                execution.connection,
                execution.state,
                message,
                execution.scope,
            )
            if suspended:
                execution.stream.resume()
                suspended = False
            self._finish(execution, lane)
            if response is not None:
                execution.state.send(response)
                execution.connection.send(response)
        except (NativeProtocolError, OSError):
            execution.connection.interrupt()
        finally:
            try:
                if suspended:
                    execution.stream.resume()
            finally:
                self._finish(execution, lane)

    def _finish(
        self,
        execution: NativeCommandExecution,
        lane: str,
    ) -> None:
        with self._lock:
            if self._active.get(lane) is execution:
                del self._active[lane]
            if self._cleanup_pending and not self._active:
                self._cleanup_pending = False
                if self._cleanup is not None:
                    self._cleanup()
