"""Backend protocol for native Computer Use adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..capability_types import PlatformProbe
from ..models import (
    BackendCapture,
    FocusSnapshot,
    MutationCommand,
    ObservedApp,
    ObservedElement,
    ObservedWindow,
)


@dataclass(frozen=True, slots=True)
class BackendError(RuntimeError):
    code: str
    message: str
    retryable: bool = False
    effect_possible: bool = False

    def __str__(self) -> str:
        return self.message


class ComputerUseBackend(Protocol):
    backend_id: str
    foreground_actions: frozenset[str]

    def probe(self) -> PlatformProbe: ...

    def list_apps(self) -> tuple[ObservedApp, ...]: ...

    def list_windows(
        self,
        app: ObservedApp | None,
    ) -> tuple[ObservedWindow, ...]: ...

    def capture(
        self,
        window: ObservedWindow,
        mode: str,
    ) -> BackendCapture: ...

    def mutate(self, command: MutationCommand) -> bool: ...

    def read_element(
        self,
        accessibility_identity: str,
    ) -> ObservedElement | None: ...

    def focus_state(self) -> FocusSnapshot: ...

    def can_restore_focus(self, snapshot: FocusSnapshot) -> bool: ...

    def restore_focus(self, snapshot: FocusSnapshot) -> bool: ...

    def release_inputs(self) -> tuple[str, ...]: ...
