from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast, final

import pytest

from birkin import uistate
from birkin.computer_use.capability_types import (
    DisplayServer,
    PermissionState,
    PlatformProbe,
)
from birkin.computer_use.runtime import UnavailableBackend
from birkin.workspace import approval_authority
from birkin.runtime import Session
from birkin.workspace import WorkspaceEvent, runtime_adapter
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter


@final
class _RuntimeSession:
    def __init__(self) -> None:
        self.cfg: dict[str, object] = {}
        self.steers: list[str] = []
        self.ask_count: int = 0

    def steer(self, text: str) -> bool:
        self.steers.append(text)
        return True

    def ask(self, text: str, *, on_text: object) -> str:
        del on_text
        self.ask_count += 1
        if self.ask_count == 1:
            raise RuntimeError("provider failed")
        return f"retried: {text}"


def test_runtime_adapter_registers_product_surface_authority_and_commands(
    tmp_path: Path,
) -> None:
    adapter = RuntimeWorkspaceAdapter(
        "surface-session", _event, workspace_root=tmp_path / "workspace"
    )

    assert adapter.surface_authority.surface_names == (
        "browser_aside", "computer_use", "office"
    )
    assert {
        "browser.start", "browser.navigate", "office.create", "office.open"
    }.issubset(adapter.handlers())
    snapshots = adapter.surface_authority.snapshots({
        "browser_aside": 0, "computer_use": 0, "office": 0
    })
    assert [snapshot.surface for snapshot in snapshots] == [
        "browser_aside", "computer_use", "office"
    ]


@final
class _GrantedBackend:
    """A platform backend that reports both permissions already granted."""

    backend_id = "test-granted"

    def probe(self) -> PlatformProbe:
        return PlatformProbe(
            platform="darwin",
            display_server=DisplayServer.QUARTZ,
            interactive=True,
            accessibility=PermissionState.GRANTED,
            screen_capture=PermissionState.GRANTED,
            responsible_process="birkin-test",
        )


def test_computer_use_surface_projects_the_selected_backend_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Given a platform backend reporting granted permissions, When the runtime
    adapter composes product surfaces, Then Computer Use projects that grant."""
    monkeypatch.setattr(
        runtime_adapter, "default_backend", lambda: _GrantedBackend()
    )
    adapter = RuntimeWorkspaceAdapter(
        "capability-session", _event, workspace_root=tmp_path / "workspace"
    )

    status = cast(
        dict[str, object], adapter.surface_authority.computer_use.snapshot()["status"]
    )

    permissions = cast(dict[str, object], status["permissions"])
    assert permissions["accessibility"] == "granted"
    assert permissions["screen_capture"] == "granted"
    assert status["permission_prompted"] is False


def test_computer_use_surface_projects_an_unavailable_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Given no supported platform backend, When the runtime adapter composes
    product surfaces, Then Computer Use projects undetermined permissions."""
    monkeypatch.setattr(
        runtime_adapter, "default_backend", lambda: UnavailableBackend()
    )
    adapter = RuntimeWorkspaceAdapter(
        "capability-session", _event, workspace_root=tmp_path / "workspace"
    )

    status = cast(
        dict[str, object], adapter.surface_authority.computer_use.snapshot()["status"]
    )

    permissions = cast(dict[str, object], status["permissions"])
    assert permissions["accessibility"] == "unknown"
    assert status["permission_prompted"] is False


def test_runtime_adapter_advertises_and_executes_jailed_file_import(
    tmp_path: Path,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    dropped = tmp_path / "outside" / "drop.txt"
    dropped.parent.mkdir()
    dropped.write_text("drop through production adapter", encoding="utf-8")
    adapter = RuntimeWorkspaceAdapter(
        "import-session", emit, workspace_root=tmp_path / "workspace"
    )

    handler = adapter.handlers()["file.import"]
    result = handler({"source_path": str(dropped)})

    reference = cast(dict[str, object], result["reference"])
    imported = tmp_path / "workspace" / "imports" / str(reference["jail_name"])
    assert imported.read_text(encoding="utf-8") == "drop through production adapter"


def test_steer_delegates_to_runtime_and_emits_canonical_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    runtime = _RuntimeSession()

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
    ) -> Session:
        del on_event
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    adapter = RuntimeWorkspaceAdapter("steer-session", emit)

    result = adapter.handlers()["chat.steer"]({"text": "  check tests  "})

    assert result == {"steered": True}
    assert runtime.steers == ["check tests"]
    assert emitted == [("turn.steered", {"text": "check tests"})]


def test_retry_replays_failed_text_as_a_new_handler_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    runtime = _RuntimeSession()

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
    ) -> Session:
        del on_event
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    adapter = RuntimeWorkspaceAdapter("retry-session", emit)
    handlers = adapter.handlers()

    with pytest.raises(RuntimeError, match="provider failed"):
        _ = handlers["chat.send"]({"text": "original intent"})
    result = handlers["chat.retry"]({})

    assert runtime.ask_count == 2
    assert result == {"reply": "retried: original intent"}
    assert emitted == [
        ("message.user", {"text": "original intent"}),
        ("message.user", {"text": "original intent"}),
        ("message.assistant.completed", {"text": "retried: original intent"}),
    ]


def _event(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
    return WorkspaceEvent(
        protocol_version=1,
        session_id="test-session",
        cursor=1,
        event_id="event-1",
        type=event_type,
        timestamp="2026-08-20T00:00:00Z",
        actor_id="test:runtime",
        command_id="command-1",
        payload=payload,
    )


def test_approval_answer_event_carries_execution_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(
        event_type: str,
        payload: dict[str, object],
    ) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return WorkspaceEvent(
            protocol_version=1,
            session_id="receipt-session",
            cursor=1,
            event_id="event-1",
            type=event_type,
            timestamp="2026-08-16T00:00:00Z",
            actor_id="web:test",
            command_id="command-1",
            payload=payload,
        )

    def decide(
        approval_id: str, *, decision: str, reason: str = ""
    ) -> dict[str, object]:
        assert decision == "approve"
        assert reason == ""
        return {
            "outcome": "approved",
            "approval_id": approval_id,
            "receipt": "exit 0: approved",
        }

    monkeypatch.setattr(approval_authority, "decide", decide)
    adapter = RuntimeWorkspaceAdapter("receipt-session", emit)

    result = adapter.handlers()["approval.answer"](
        {"approval_id": "abc123def456", "decision": "approve"}
    )

    assert result == {
        "outcome": "approved",
        "approval_id": "abc123def456",
        "receipt": "exit 0: approved",
    }
    assert emitted == [
        (
            "approval.answered",
            {
                "approval_id": "abc123def456",
                "decision": "approve",
                "outcome": "approved",
                "receipt": "exit 0: approved",
            },
        )
    ]


def _runtime_adapter() -> tuple[
    RuntimeWorkspaceAdapter,
    list[tuple[str, dict[str, object]]],
]:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(
        event_type: str,
        payload: dict[str, object],
    ) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return WorkspaceEvent(
            protocol_version=1,
            session_id="receipt-session",
            cursor=1,
            event_id="event-1",
            type=event_type,
            timestamp="2026-08-16T00:00:00Z",
            actor_id="web:test",
            command_id="command-1",
            payload=payload,
        )

    return RuntimeWorkspaceAdapter("receipt-session", emit), emitted


def test_tool_end_error_distinguishable_from_success() -> None:
    adapter, emitted = _runtime_adapter()

    adapter._runtime_event(
        "tool_end",
        {"name": "grep", "is_error": False, "content": "ok"},
    )
    adapter._runtime_event(
        "tool_end",
        {"name": "grep", "is_error": True, "content": "boom"},
    )

    assert [event_type for event_type, _payload in emitted] == [
        "tool.completed",
        "tool.failed",
    ]
    assert emitted[0][1]["state"] == "completed"
    assert emitted[1][1]["state"] == "failed"
    assert emitted[0][1] != emitted[1][1]


def test_aborted_tool_maps_failed() -> None:
    adapter, emitted = _runtime_adapter()

    adapter._runtime_event(
        "tool_end",
        {"content": "aborted", "is_error": True},
    )

    assert emitted[0][0] == "tool.failed"
    assert emitted[0][1]["state"] == "failed"


def test_all_emitted_states_in_uistate_vocabulary() -> None:
    adapter, emitted = _runtime_adapter()
    events = (
        "tool_start",
        "tool_end",
        "subagent.start",
        "subagent.done",
        "compact",
        "steer",
    )

    for event in events:
        adapter._runtime_event(event, {})
        adapter._runtime_event(event, {"is_error": True})
    adapter._runtime_event("no_such_event", {})

    for _event_type, payload in emitted:
        assert payload["state"] in uistate.UI_STATES


@pytest.mark.parametrize(
    ("payload", "expected_event_type", "expected_state"),
    [
        ({}, "tool.completed", "completed"),
        ({"is_error": None}, "tool.completed", "completed"),
        ({"is_error": 0}, "tool.completed", "completed"),
        ({"is_error": ""}, "tool.completed", "completed"),
        ({"is_error": False}, "tool.completed", "completed"),
        ({"is_error": True}, "tool.failed", "failed"),
        ({"is_error": 1}, "tool.failed", "failed"),
        ({"is_error": "false"}, "tool.failed", "failed"),
        ({"is_error": ["error"]}, "tool.failed", "failed"),
    ],
)
def test_tool_end_is_error_uses_truthiness(
    payload: dict[str, object],
    expected_event_type: str,
    expected_state: str,
) -> None:
    adapter, emitted = _runtime_adapter()

    adapter._runtime_event("tool_end", payload)

    assert emitted[0][0] == expected_event_type
    assert emitted[0][1]["state"] == expected_state


def test_event_type_table_pin() -> None:
    """Reverse the earlier pin after tool.failed consumer support was verified.

    Support exists in snapshot.py, workspace_terminal.py, and index.html.
    """
    adapter, emitted = _runtime_adapter()
    runtime_events = (
        ("tool_start", {}),
        ("tool_end", {}),
        ("tool_end", {"is_error": True}),
        ("subagent.start", {}),
        ("subagent.done", {}),
        ("compact", {}),
        ("steer", {}),
        ("no_such_event", {}),
    )

    for event, payload in runtime_events:
        adapter._runtime_event(event, payload)

    assert [event_type for event_type, _payload in emitted] == [
        "tool.started",
        "tool.completed",
        "tool.failed",
        "task.updated",
        "task.updated",
        "progress.updated",
        "progress.updated",
        "progress.updated",
    ]
