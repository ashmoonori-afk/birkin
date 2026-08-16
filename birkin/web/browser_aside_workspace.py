"""Workspace-scoped Browser Aside service and mutation authority."""

from __future__ import annotations

from threading import RLock
from time import monotonic
from typing import cast, final

from birkin.browser_aside_control import (
    BrowserControlConflict,
    browser_control_authority,
    browser_workspace_registry,
)
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_store import FrameBlob


@final
class BrowserApiWorkspace:
    def __init__(self, workspace_id: str) -> None:
        self._service = browser_workspace_registry().resolve(
            workspace_id,
            "web",
        )
        self._control = browser_control_authority(monotonic)

    def status(self) -> dict[str, object]:
        return self._with_control(self._service.status())

    @property
    def service(self) -> object:
        return self._service

    def start(self, actor_id: str) -> tuple[dict[str, object], bool]:
        lease = self._control.acquire(actor_id, "human")
        status, created = self._service.start(
            actor_id=actor_id,
            control_epoch=lease.epoch,
        )
        return self._with_control(status), created

    def frame(
        self,
        *,
        generation: int,
    ) -> tuple[FrameBlob, dict[str, object]]:
        return self._service.frame(generation=generation)

    def navigate(
        self,
        url: str,
        payload: dict[str, object],
        *,
        actor_id: str,
    ) -> dict[str, object]:
        generation, revision = self._authorize(payload, actor_id)
        return self._with_control(self._service.navigate(
            url,
            expected_generation=generation,
            expected_revision=revision,
        ))

    def close(
        self,
        payload: dict[str, object],
        *,
        actor_id: str,
    ) -> dict[str, object]:
        _, _ = self._authorize(payload, actor_id)
        result = self._service.close()
        epoch = cast(int, payload["control_epoch"])
        self._control.release(actor_id, epoch)
        return result

    def force_close(self) -> dict[str, object]:
        result = self._service.close()
        lease = self._control.current()
        if lease is not None:
            self._control.release(lease.owner_id, lease.epoch)
        return result

    def _authorize(
        self,
        payload: dict[str, object],
        actor_id: str,
    ) -> tuple[int, int]:
        generation = payload.get("browser_generation")
        revision = payload.get("browser_revision")
        epoch = payload.get("control_epoch")
        sequence = payload.get("control_sequence")
        current = self._service.status()
        if (
            not _integer(generation)
            or generation != current["browser_generation"]
        ):
            raise BrowserAsideError(
                "stale_browser_generation",
                "Browser generation is stale.",
                409,
            )
        if (
            not _integer(revision)
            or revision != current["browser_revision"]
        ):
            raise BrowserAsideError(
                "stale_browser_revision",
                "Browser revision is stale.",
                409,
            )
        if not _integer(epoch) or not _integer(sequence):
            raise BrowserAsideError(
                "stale_control_epoch",
                "Browser control lease is stale.",
                409,
            )
        generation_int = cast(int, generation)
        revision_int = cast(int, revision)
        epoch_int = cast(int, epoch)
        sequence_int = cast(int, sequence)
        try:
            self._control.authorize(
                actor_id,
                epoch_int,
                sequence_int,
            )
        except BrowserControlConflict as exc:
            raise BrowserAsideError(
                "stale_control_epoch",
                "Browser control lease is stale or not owned.",
                409,
            ) from exc
        return generation_int, revision_int

    def _with_control(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        lease = self._control.current()
        return {
            **payload,
            "control_owner_id": lease.owner_id if lease else None,
            "control_owner_kind": lease.owner_kind if lease else None,
            "control_epoch": lease.epoch if lease else 0,
        }


_WORKSPACES: dict[str, BrowserApiWorkspace] = {}
_LOCK = RLock()


def browser_api_workspace(workspace_id: str) -> BrowserApiWorkspace:
    if not workspace_id:
        raise ValueError("workspace id is required")
    with _LOCK:
        workspace = _WORKSPACES.get(workspace_id)
        if workspace is None:
            workspace = BrowserApiWorkspace(workspace_id)
            _WORKSPACES[workspace_id] = workspace
        return workspace


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
