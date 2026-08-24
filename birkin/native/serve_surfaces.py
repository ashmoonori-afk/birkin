"""Selected-session surface projection for the native bridge process."""

from __future__ import annotations

from collections.abc import Mapping
from typing import final

from birkin.native.product_surfaces import SurfaceSnapshot
from birkin.workspace.hub import WorkspaceHub
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter


@final
class SelectedSurfaceAuthority:
    """Project product surfaces belonging to the hub's selected session."""

    def __init__(
        self,
        hub: WorkspaceHub,
        adapters: Mapping[str, RuntimeWorkspaceAdapter],
    ) -> None:
        self._hub = hub
        self._adapters = adapters

    def _current(self) -> RuntimeWorkspaceAdapter:
        return self._adapters[self._hub.snapshot().session_id]

    @property
    def surface_names(self) -> tuple[str, ...]:
        return self._current().surface_authority.surface_names

    def snapshots(
        self,
        requested: Mapping[str, int],
    ) -> tuple[SurfaceSnapshot, ...]:
        return self._current().surface_authority.snapshots(requested)

    def live_snapshot(self, surface: str) -> SurfaceSnapshot | None:
        return self._current().surface_authority.live_snapshot(surface)
