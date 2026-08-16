"""Closed Browser event bridge into the workspace journal envelope."""

from __future__ import annotations

import json
from collections.abc import Callable
from threading import RLock
from typing import cast, final

BROWSER_EVENT_TYPES = frozenset({
    "browser.started",
    "browser.stopped",
    "tab.opened",
    "tab.selected",
    "tab.updated",
    "tab.closed",
    "navigation.started",
    "navigation.committed",
    "navigation.finished",
    "viewport.resized",
    "viewport.invalidated",
    "viewport.ready",
    "action.requested",
    "action.started",
    "action.finished",
    "download.requested",
    "download.started",
    "download.finished",
    "dialog.opened",
    "dialog.resolved",
    "error.raised",
    "error.cleared",
})
_TERMINAL_TYPES = frozenset({"browser.stopped"})
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "bytes",
        "content",
        "data",
        "base64",
        "path",
        "url",
        "title",
        "cookie",
        "authorization",
    }
)
MAX_BROWSER_PAYLOAD_BYTES = 8_192
MAX_EVENT_BYTES = 65_536


@final
class BrowserEventBridge:
    def __init__(
        self,
        *,
        session_id: str,
        actor_id: str,
        clock: Callable[[], float],
        append: Callable[[dict[str, object]], None],
        browser_session_id: str | None = None,
        browser_generation: int = 0,
        browser_revision: int = 0,
        cursor_start: int = 0,
    ) -> None:
        self._session_id = session_id
        self._actor_id = actor_id
        self._clock = clock
        self._append = append
        self._browser_session_id = (
            browser_session_id or session_id
        )
        self._browser_generation = browser_generation
        self._browser_revision = browser_revision
        self._cursor = cursor_start
        self._terminal: dict[str, dict[str, object]] = {}
        self._viewport_generations: set[int] = set()
        self._lock = RLock()

    def emit(
        self,
        event_type: str,
        *,
        command_id: str | None,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if event_type not in BROWSER_EVENT_TYPES:
            raise ValueError(f"unknown browser event type: {event_type}")
        self._validate_payload(payload)
        if len(json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()) > MAX_BROWSER_PAYLOAD_BYTES:
            raise ValueError("browser event payload exceeds size limit")
        with self._lock:
            if event_type in _TERMINAL_TYPES:
                existing = self._terminal.get(event_type)
                if existing is not None:
                    return existing
            self._cursor += 1
            event: dict[str, object] = {
                "protocol_version": 1,
                "event_schema_version": 1,
                "session_id": self._session_id,
                "browser_session_id": self._browser_session_id,
                "browser_generation": self._browser_generation,
                "browser_revision": self._browser_revision,
                "cursor": self._cursor,
                "event_id": f"browser-event-{self._cursor}",
                "type": event_type,
                "timestamp": self._clock(),
                "actor_id": self._actor_id,
                "command_id": command_id,
                "payload": dict(payload),
            }
            encoded = json.dumps(
                event,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            if len(encoded) > MAX_EVENT_BYTES:
                raise ValueError("browser event exceeds size limit")
            self._append(event)
            if event_type in _TERMINAL_TYPES:
                self._terminal[event_type] = event
            return event

    @property
    def cursor(self) -> int:
        with self._lock:
            return self._cursor

    def set_authority(self, actor_id: str) -> None:
        if not actor_id:
            raise ValueError("browser event actor is required")
        with self._lock:
            self._actor_id = actor_id

    def set_browser_revision(
        self,
        *,
        generation: int,
        revision: int,
    ) -> None:
        with self._lock:
            self._browser_generation = generation
            self._browser_revision = revision

    def finish_operation(
        self,
        operation_id: str,
        *,
        command_id: str,
        result: str,
    ) -> dict[str, object]:
        return self.emit(
            "navigation.finished",
            command_id=command_id,
            payload={
                "operation_id": operation_id,
                "result": result,
            },
        )

    def viewport_ready(
        self,
        *,
        generation: int,
        frame_revision: int,
        frame_digest: str,
        frame_ref: str,
    ) -> dict[str, object] | None:
        with self._lock:
            if generation in self._viewport_generations:
                return None
            self._viewport_generations.add(generation)
        return self.emit(
            "viewport.ready",
            command_id=None,
            payload={
                "generation": generation,
                "frame_revision": frame_revision,
                "frame_digest": frame_digest,
                "frame_ref": frame_ref,
            },
        )

    def repaint(self, generation: int) -> None:
        del generation

    def replay(
        self,
        events: tuple[dict[str, object], ...],
        reducer: Callable[[dict[str, object]], None],
    ) -> None:
        for event in events:
            reducer(dict(event))

    @classmethod
    def _validate_payload(
        cls,
        payload: dict[str, object],
    ) -> None:
        for key, value in payload.items():
            if key.lower() in _FORBIDDEN_PAYLOAD_KEYS:
                raise ValueError("browser event payload is private")
            if isinstance(value, bytes):
                raise TypeError("browser event payload cannot contain bytes")
            if isinstance(value, dict):
                nested = cast(dict[object, object], value)
                if not all(isinstance(inner, str) for inner in nested):
                    raise TypeError("browser event keys must be strings")
                cls._validate_payload(
                    cast(dict[str, object], nested)
                )
            if isinstance(value, (list, tuple)):
                for item in cast(list[object] | tuple[object, ...], value):
                    cls._validate_payload({"item": item})


def browser_event_bridge(
    *,
    session_id: str,
    actor_id: str,
    clock: Callable[[], float],
    append: Callable[[dict[str, object]], None],
    browser_session_id: str | None = None,
    browser_generation: int = 0,
    browser_revision: int = 0,
    cursor_start: int = 0,
) -> BrowserEventBridge:
    return BrowserEventBridge(
        session_id=session_id,
        actor_id=actor_id,
        clock=clock,
        append=append,
        browser_session_id=browser_session_id,
        browser_generation=browser_generation,
        browser_revision=browser_revision,
        cursor_start=cursor_start,
    )
