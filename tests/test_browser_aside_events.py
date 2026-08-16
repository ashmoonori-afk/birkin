from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from types import ModuleType
from typing import Protocol, cast


class _EventBridge(Protocol):
    def emit(
        self,
        event_type: str,
        *,
        command_id: str | None,
        payload: dict[str, object],
    ) -> dict[str, object]: ...

    def finish_operation(
        self,
        operation_id: str,
        *,
        command_id: str,
        result: str,
    ) -> dict[str, object]: ...

    def viewport_ready(
        self,
        *,
        generation: int,
        frame_revision: int,
        frame_digest: str,
        frame_ref: str,
    ) -> dict[str, object] | None: ...

    def repaint(self, generation: int) -> None: ...

    def set_authority(self, actor_id: str) -> None: ...

    def replay(
        self,
        events: tuple[dict[str, object], ...],
        reducer: Callable[[dict[str, object]], None],
    ) -> None: ...


class _EventModule(Protocol):
    BROWSER_EVENT_TYPES: frozenset[str]

    def browser_event_bridge(
        self,
        *,
        session_id: str,
        actor_id: str,
        clock: Callable[[], float],
        append: Callable[[dict[str, object]], None],
        browser_session_id: str | None = None,
        cursor_start: int = 0,
    ) -> _EventBridge: ...


def _module() -> _EventModule:
    module: ModuleType = importlib.import_module(
        "birkin.browser_aside_events"
    )
    return cast(_EventModule, cast(object, module))


def _bridge(
    events: list[dict[str, object]],
) -> _EventBridge:
    return _module().browser_event_bridge(
        session_id="workspace-1",
        actor_id="human:web",
        clock=lambda: 100.0,
        append=events.append,
    )


def test_browser_event_uses_existing_workspace_envelope() -> None:
    events: list[dict[str, object]] = []
    event = _bridge(events).emit(
        "browser.started",
        command_id="cmd-1",
        payload={"browser_session_id": "browser-1", "generation": 1},
    )
    assert set(event) == {
        "protocol_version",
        "event_schema_version",
        "session_id",
        "browser_session_id",
        "browser_generation",
        "browser_revision",
        "cursor",
        "event_id",
        "type",
        "timestamp",
        "actor_id",
        "command_id",
        "payload",
    }
    assert event["session_id"] == "workspace-1"
    assert event["cursor"] == 1
    assert events == [event]


def test_workspace_identity_cursor_and_actor_survive_runtime_rebind() -> None:
    events: list[dict[str, object]] = []
    bridge = _module().browser_event_bridge(
        session_id="workspace-1",
        browser_session_id="browser-9",
        actor_id="human:web:a",
        clock=lambda: 100.0,
        append=events.append,
        cursor_start=7,
    )
    bridge.set_authority("human:web:b")
    event = bridge.emit(
        "browser.started",
        command_id=None,
        payload={"generation": 2},
    )
    assert event["session_id"] == "workspace-1"
    assert event["browser_session_id"] == "browser-9"
    assert event["actor_id"] == "human:web:b"
    assert event["cursor"] == 8


def test_async_event_retains_originating_command_causality() -> None:
    events: list[dict[str, object]] = []
    bridge = _bridge(events)
    started = bridge.emit(
        "navigation.started",
        command_id="cmd-77",
        payload={"operation_id": "nav-2"},
    )
    finished = bridge.finish_operation(
        "nav-2",
        command_id="cmd-77",
        result="succeeded",
    )
    assert started["command_id"] == finished["command_id"] == "cmd-77"
    assert finished["payload"] == {
        "operation_id": "nav-2",
        "result": "succeeded",
    }
    assert [event["cursor"] for event in events] == [1, 2]


def test_terminal_events_are_exactly_once_and_ordered() -> None:
    events: list[dict[str, object]] = []
    bridge = _bridge(events)
    _ = bridge.emit(
        "tab.updated",
        command_id=None,
        payload={"generation": 1},
    )
    _ = bridge.emit(
        "error.raised",
        command_id=None,
        payload={"code": "browser_crashed"},
    )
    stopped = bridge.emit(
        "browser.stopped",
        command_id=None,
        payload={"cleanup": "clean"},
    )
    duplicate = bridge.emit(
        "browser.stopped",
        command_id=None,
        payload={"cleanup": "clean"},
    )
    assert [event["type"] for event in events] == [
        "tab.updated",
        "error.raised",
        "browser.stopped",
    ]
    assert duplicate == stopped


def test_browser_event_privacy_keeps_only_digest_and_ref() -> None:
    events: list[dict[str, object]] = []
    bridge = _bridge(events)
    event = bridge.viewport_ready(
        generation=3,
        frame_revision=9,
        frame_digest="hmac-sha256:" + "a" * 64,
        frame_ref="birkin-frame:v1:opaque",
    )
    assert event is not None
    encoded = json.dumps(event)
    for forbidden in ("data:image", "base64", "JFIF", "/Users/", "https://"):
        assert forbidden not in encoded
    assert set(cast(dict[str, object], event["payload"])) == {
        "generation",
        "frame_revision",
        "frame_digest",
        "frame_ref",
    }


def test_replay_never_invokes_browser_mutation() -> None:
    events: list[dict[str, object]] = []
    bridge = _bridge(events)
    _ = bridge.emit(
        "navigation.finished",
        command_id="cmd-1",
        payload={"operation_id": "nav-1", "result": "succeeded"},
    )
    reduced: list[dict[str, object]] = []
    bridge.replay(tuple(events), reduced.append)
    assert reduced == events


def test_repaints_coalesce_without_journal_growth() -> None:
    events: list[dict[str, object]] = []
    bridge = _bridge(events)
    first = bridge.viewport_ready(
        generation=5,
        frame_revision=1,
        frame_digest="hmac-sha256:" + "b" * 64,
        frame_ref="birkin-frame:v1:first",
    )
    assert first is not None
    for _ in range(10_000):
        bridge.repaint(5)
    duplicate = bridge.viewport_ready(
        generation=5,
        frame_revision=10_001,
        frame_digest="hmac-sha256:" + "c" * 64,
        frame_ref="birkin-frame:v1:last",
    )
    assert duplicate is None
    assert len(events) == 1


def test_event_taxonomy_covers_every_contract_family() -> None:
    assert _module().BROWSER_EVENT_TYPES == frozenset({
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
