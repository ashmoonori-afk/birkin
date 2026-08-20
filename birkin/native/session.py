"""Reconnect-safe projection of canonical workspace state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, final

from birkin.native.projection import (
    public_native_mapping,
    public_workspace_event,
)
from birkin.native.protocol import NativeProtocolError
from birkin.workspace.records import WorkspaceEvent, WorkspaceSnapshot


class WorkspaceProjectionSource(Protocol):
    def snapshot(self) -> WorkspaceSnapshot: ...

    def events(self, *, after: int = 0) -> tuple[WorkspaceEvent, ...]: ...


@final
@dataclass(frozen=True, slots=True)
class ProjectionBatch:
    instance_id: str
    snapshot: dict[str, object] | None
    events: tuple[dict[str, object], ...]
    reset_reason: str | None


@final
class NativeProjectionSession:
    """Render snapshots and cursor-contiguous public event replay."""

    def __init__(
        self,
        source: WorkspaceProjectionSource,
        *,
        instance_id: str,
    ) -> None:
        if not instance_id:
            raise ValueError("instance_id cannot be empty")
        self._source = source
        self.instance_id = instance_id

    def subscribe(
        self,
        *,
        after_cursor: int,
        known_instance_id: str | None,
    ) -> ProjectionBatch:
        if (
            isinstance(after_cursor, bool)
            or after_cursor < 0
        ):
            raise NativeProtocolError(
                "E_BODY",
                "after_cursor must be a non-negative integer",
            )
        snapshot = self._source.snapshot()
        reset_reason = self._reset_reason(
            after_cursor=after_cursor,
            known_instance_id=known_instance_id,
            current_cursor=snapshot.cursor,
        )
        if reset_reason is not None:
            return ProjectionBatch(
                instance_id=self.instance_id,
                snapshot=_reconnect_snapshot(snapshot),
                events=(),
                reset_reason=reset_reason,
            )
        events = self._source.events(after=after_cursor)
        if not _cursors_are_contiguous(events, after_cursor=after_cursor):
            return ProjectionBatch(
                instance_id=self.instance_id,
                snapshot=_reconnect_snapshot(snapshot),
                events=(),
                reset_reason="cursor_gap",
            )
        return ProjectionBatch(
            instance_id=self.instance_id,
            snapshot=None,
            events=tuple(public_workspace_event(event) for event in events),
            reset_reason=None,
        )

    def _reset_reason(
        self,
        *,
        after_cursor: int,
        known_instance_id: str | None,
        current_cursor: int,
    ) -> str | None:
        if known_instance_id is None:
            return "initial"
        if known_instance_id != self.instance_id:
            return "instance_changed"
        if after_cursor > current_cursor:
            return "cursor_ahead"
        return None


def _reconnect_snapshot(snapshot: WorkspaceSnapshot) -> dict[str, object]:
    public = public_native_mapping(snapshot.to_json())
    terminals = public.get("terminals")
    if isinstance(terminals, list):
        for terminal in terminals:
            if isinstance(terminal, dict):
                terminal["lease"] = None
                terminal["read_only"] = True
    return public


def _cursors_are_contiguous(
    events: tuple[WorkspaceEvent, ...],
    *,
    after_cursor: int,
) -> bool:
    return all(
        event.cursor == after_cursor + index
        for index, event in enumerate(events, start=1)
    )
