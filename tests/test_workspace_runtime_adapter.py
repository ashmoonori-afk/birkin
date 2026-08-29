from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import threading
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


@final
class _ActiveRuntimeSession:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.cfg: dict[str, object] = {}
        self.abort = threading.Event()
        self.steers: list[str] = []
        self._started = started
        self._release = release

    def ask(self, text: str, *, on_text: object) -> str:
        del on_text
        self._started.set()
        if not self._release.wait(timeout=10):
            raise AssertionError("test did not release active runtime")
        return text

    def steer(self, text: str) -> bool:
        self.steers.append(text)
        return True


@final
class _CapturingRuntimeSession:
    def __init__(self) -> None:
        self.cfg: dict[str, object] = {}
        self.abort = threading.Event()
        self.prompts: list[str] = []

    def ask(self, text: str, *, on_text: object) -> str:
        del on_text
        self.prompts.append(text)
        if '<approval-outcome' in text and 'outcome="approved"' in text:
            return "승인된 작업이 완료되었습니다."
        if "<approval-outcome" in text:
            return "승인된 작업을 완료하지 못했습니다."
        return f"agent saw: {text}"

    def steer(self, _text: str) -> bool:
        return False


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
    _ = dropped.write_text("drop through production adapter", encoding="utf-8")
    adapter = RuntimeWorkspaceAdapter(
        "import-session", emit, workspace_root=tmp_path / "workspace"
    )

    handler = adapter.handlers()["file.import"]
    result = handler({"source_path": str(dropped)})

    reference = cast(dict[str, object], result["reference"])
    imported = tmp_path / "workspace" / "imports" / str(reference["jail_name"])
    assert imported.read_text(encoding="utf-8") == "drop through production adapter"


def test_chat_send_accepts_only_unchanged_imports_from_its_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _RuntimeSession()
    runtime.ask_count = 1

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
    ) -> Session:
        del on_event
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    workspace = tmp_path / "workspace"
    source = tmp_path / "attachment.txt"
    _ = source.write_text("trusted attachment", encoding="utf-8")
    adapter = RuntimeWorkspaceAdapter("attachment-session", _event, workspace_root=workspace)
    imported = adapter.handlers()["file.import"]({"source_path": str(source)})
    reference = cast(dict[str, object], imported["reference"])

    result = adapter.handlers()["chat.send"]({
        "text": "inspect this",
        "attachments": [reference],
    })

    assert result["attachments"] == [reference]
    assert "attachment.txt" in cast(str, result["reply"])

    jailed = workspace / "imports" / str(reference["jail_name"])
    _ = jailed.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        _ = adapter.handlers()["chat.send"]({
            "text": "inspect this",
            "attachments": [reference],
        })
    jailed.unlink()
    with pytest.raises(ValueError, match="deleted"):
        _ = adapter.handlers()["chat.send"]({
            "text": "inspect this",
            "attachments": [reference],
        })


def test_chat_send_rejects_unknown_and_cross_session_imports(tmp_path: Path) -> None:
    source = tmp_path / "attachment.txt"
    _ = source.write_text("trusted attachment", encoding="utf-8")
    first = RuntimeWorkspaceAdapter(
        "first-session", _event, workspace_root=tmp_path / "workspace"
    )
    second = RuntimeWorkspaceAdapter(
        "second-session", _event, workspace_root=tmp_path / "workspace"
    )
    imported = first.handlers()["file.import"]({"source_path": str(source)})
    reference = cast(dict[str, object], imported["reference"])

    with pytest.raises(ValueError, match="unknown.*session"):
        _ = second.handlers()["chat.send"]({"text": "inspect", "attachments": [reference]})

    unknown = dict(reference)
    unknown["import_id"] = "import-00000000000000000000000000000000"
    with pytest.raises(ValueError, match="unknown.*session"):
        _ = first.handlers()["chat.send"]({"text": "inspect", "attachments": [unknown]})


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


def test_turn_controls_mutate_the_active_runtime_without_waiting_for_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    runtime = _ActiveRuntimeSession(started, release)

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
    ) -> Session:
        del on_event
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    adapter = RuntimeWorkspaceAdapter("control-session", emit)
    handlers = adapter.handlers()
    errors: list[BaseException] = []

    def send() -> None:
        try:
            _ = handlers["chat.send"]({"text": "work"})
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=send)
    thread.start()
    try:
        assert started.wait(timeout=1)
        assert handlers["chat.interrupt"]({}) == {"interrupted": True}
        assert runtime.abort.is_set()
        assert handlers["chat.steer"]({"text": "redirect"}) == {"steered": True}
        assert runtime.steers == ["redirect"]
        assert handlers["chat.resume"]({}) == {"resumed": True}
        assert not runtime.abort.is_set()
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert errors == []
    assert (
        "progress.updated",
        {
            "summary": "Turn interrupted.",
            "status": "interrupted",
            "ui_state": "paused",
        },
    ) in emitted


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
        (
            "progress.updated",
            {
                "summary": "Assistant response failed.",
                "status": "failed",
                "ui_state": "failed",
                "refusal_code": "E_RUNTIME",
                "retryable": True,
            },
        ),
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


def test_approval_answer_summary_is_injected_into_next_agent_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _CapturingRuntimeSession()
    adapter = RuntimeWorkspaceAdapter(
        "approval-context-session",
        _event,
        workspace_root=tmp_path / "workspace",
    )
    setattr(adapter, "_session", cast(Session, cast(object, runtime)))

    def approved_decide(
        _approval_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, object]:
        assert decision == "approve"
        assert reason == ""
        return {
            "outcome": "approved",
            "receipt": '{"job_id":"job-context","outcome":"saved"}',
        }

    monkeypatch.setattr(
        approval_authority,
        "decide",
        approved_decide,
    )

    _ = adapter.handlers()["approval.answer"](
        {"approval_id": "approval-context", "decision": "approve"}
    )
    first = adapter.handlers()["chat.send"]({"text": "결과를 알려줘"})
    second = adapter.handlers()["chat.send"]({"text": "다음 질문"})

    assert "<approval-outcome" in runtime.prompts[0]
    assert 'lang="ko"' in runtime.prompts[0]
    assert 'approval_id="approval-context"' in runtime.prompts[0]
    assert 'outcome="approved"' in runtime.prompts[0]
    assert "결과를 알려줘" in runtime.prompts[0]
    assert "<approval-outcome" not in runtime.prompts[1]
    assert first["reply"] == "승인된 작업이 완료되었습니다."
    assert second["reply"] == "agent saw: 다음 질문"


def test_failed_approval_summary_is_injected_into_next_agent_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _CapturingRuntimeSession()
    adapter = RuntimeWorkspaceAdapter(
        "approval-failure-context-session",
        _event,
        workspace_root=tmp_path / "workspace",
    )
    setattr(adapter, "_session", cast(Session, cast(object, runtime)))

    def failed_decide(
        _approval_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, object]:
        assert decision == "approve"
        assert reason == ""
        return {
            "outcome": "execution_failed",
            "error": "export denied",
        }

    monkeypatch.setattr(
        approval_authority,
        "decide",
        failed_decide,
    )

    _ = adapter.handlers()["approval.answer"](
        {"approval_id": "approval-failed", "decision": "approve"}
    )
    response = adapter.handlers()["chat.send"]({"text": "실패 원인을 알려줘"})

    assert 'approval_id="approval-failed"' in runtime.prompts[0]
    assert 'outcome="execution_failed"' in runtime.prompts[0]
    assert 'lang="ko"' in runtime.prompts[0]
    assert "export denied" in runtime.prompts[0]
    assert response["reply"] == "승인된 작업을 완료하지 못했습니다."


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
    runtime_events: tuple[tuple[str, dict[str, object]], ...] = (
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
def test_runtime_adapter_registers_the_working_memory_command(tmp_path: Path) -> None:
    """Given the production runtime adapter, When its handlers are read, Then
    Working Memory mutation is registered so the shell can advertise it."""
    adapter = RuntimeWorkspaceAdapter(
        "memory-session", _event, workspace_root=tmp_path / "workspace"
    )

    assert "memory.write" in adapter.handlers()
