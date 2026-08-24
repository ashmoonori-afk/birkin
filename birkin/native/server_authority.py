"""Authority contracts and command routing for the native bridge."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, final, runtime_checkable

from birkin.native.bridge_commands import WorkspaceCommandAuthority
from birkin.native.product_surfaces import SurfaceSnapshot
from birkin.native.session import WorkspaceProjectionSource
from birkin.workspace import CommandReceipt, SessionPreset, WorkspaceCommand
from birkin.workspace.contracts import CONTROL_COMMAND_TYPES
from birkin.workspace.records import WorkspaceEvent


class CommandAuthority(Protocol):
    @property
    def supported_commands(self) -> frozenset[str]: ...

    def submit(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt: ...


@runtime_checkable
class ControlCommandAuthority(Protocol):
    def submit_control(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt: ...


class SurfaceProjectionAuthority(Protocol):
    @property
    def surface_names(self) -> tuple[str, ...]: ...

    def snapshots(
        self,
        requested: Mapping[str, int],
    ) -> tuple[SurfaceSnapshot, ...]: ...

    def live_snapshot(self, surface: str) -> SurfaceSnapshot | None: ...


class WorkspaceAuthority(
    WorkspaceProjectionSource,
    WorkspaceCommandAuthority,
    Protocol,
):
    @property
    def supported_commands(self) -> frozenset[str]: ...

    @property
    def session_presets(self) -> tuple[SessionPreset, ...]: ...

    def add_event_listener(
        self,
        listener: Callable[[WorkspaceEvent], None],
    ) -> Callable[[], None]: ...


@final
class CommandRouter:
    """Route workspace, session, config, and control commands by authority."""

    def __init__(
        self,
        workspace: CommandAuthority,
        session: CommandAuthority | None,
        config: CommandAuthority | None,
    ) -> None:
        self._workspace = workspace
        self._session = session
        self._config = config

    @property
    def supported_commands(self) -> frozenset[str]:
        commands = set(self._workspace.supported_commands)
        if self._session is not None:
            commands.update(
                command
                for command in self._session.supported_commands
                if command.startswith("session.")
            )
        if self._config is not None and "config.set" in self._config.supported_commands:
            commands.add("config.set")
        return frozenset(commands)

    def submit(
        self,
        command: WorkspaceCommand,
        *,
        actor_id: str,
    ) -> CommandReceipt:
        if command.type in CONTROL_COMMAND_TYPES and isinstance(
            self._workspace, ControlCommandAuthority
        ):
            return self._workspace.submit_control(command, actor_id=actor_id)
        authority = self._workspace
        if command.type.startswith("session.") and self._session is not None:
            authority = self._session
        elif command.type == "config.set" and self._config is not None:
            authority = self._config
        return authority.submit(command, actor_id=actor_id)
