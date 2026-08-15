"""Terminal unified-workspace parity and compatibility contracts."""

from __future__ import annotations

import importlib
import types
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

import pytest

from birkin import dash, repl, slashcommands, workbench, workspace_terminal
from birkin.runtime import ConfigError, Session
from birkin.ui import cell_width
from birkin.workspace import (
    WorkspaceCommand,
    WorkspaceEvent,
    WorkspaceHub,
    WorkspaceService,
)
from birkin.workspace import runtime_adapter
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.web import server as web_server

EXPECTED_PANEL_KEYS = (
    "tasks_runs",
    "approvals",
    "files_evidence",
    "sessions_history",
    "activity_logs",
    "cron",
    "memory_skills",
    "checkpoints_restore",
    "settings_status",
)


def test_terminal_surface_parity(tmp_path: Path) -> None:
    service = WorkspaceService(
        root=tmp_path,
        session_id="terminal-parity",
        handlers={},
    )
    snapshot = service.snapshot()

    assert tuple(panel.key for panel in snapshot.panels) == EXPECTED_PANEL_KEYS
    assert snapshot.composer.can_send is True
    assert snapshot.conversation == ()
    assert snapshot.status.connection == "connected"


def test_terminal_snapshot_prefers_canonical_journal(
    tmp_path: Path,
) -> None:
    service: WorkspaceService

    def handler(payload: dict[str, object]) -> dict[str, object]:
        _ = service.emit("message.user", {"text": str(payload["text"])})
        _ = service.emit(
            "message.assistant.completed",
            {"text": "canonical reply"},
        )
        return {"reply": "canonical reply"}

    service = WorkspaceService(
        root=tmp_path,
        session_id="canonical-terminal",
        handlers={"chat.send": handler},
    )
    command = WorkspaceCommand.parse(
        {
            "protocol_version": 1,
            "command_id": "canonical-message",
            "expected_cursor": 0,
            "type": "chat.send",
            "payload": {"text": "canonical question"},
            "client_context": {
                "surface": "terminal",
                "view_id": "local",
            },
        }
    )
    _ = service.submit(command, actor_id="terminal:local")
    fake = types.SimpleNamespace(
        workspace_snapshot=service.snapshot,
        agent=types.SimpleNamespace(messages=[]),
    )

    rendered = workspace_terminal.snapshot(
        cast(Session, cast(object, fake))
    )
    conversation = cast(
        list[dict[str, object]],
        rendered["conversation"],
    )
    assert [item["text"] for item in conversation] == [
        "canonical question",
        "canonical reply",
    ]


def test_runtime_snapshot_hydrates_existing_cron_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WorkspaceService(
        root=tmp_path,
        session_id="hydrated",
        handlers={},
    )
    fake_session = types.SimpleNamespace()

    def fake_build(*_args: object, **_kwargs: object) -> Session:
        return cast(Session, cast(object, fake_session))

    monkeypatch.setattr(
        runtime_adapter,
        "build_session",
        fake_build,
    )
    def hydrated_workbench(_session: object) -> dict[str, object]:
        return {
            "cron": [
                {
                    "id": "cron-sentinel",
                    "name": "Nightly workspace review",
                    "status": "active",
                }
            ]
        }

    monkeypatch.setattr(workbench, "snapshot", hydrated_workbench)
    def unexpected_event(
        _event_type: str,
        _payload: dict[str, object],
    ) -> WorkspaceEvent:
        raise AssertionError("unexpected event")

    adapter = RuntimeWorkspaceAdapter("hydrated", unexpected_event)

    enriched = adapter.enrich_snapshot(service.snapshot()).to_json()
    panels = cast(list[dict[str, object]], enriched["panels"])
    cron = next(panel for panel in panels if panel["key"] == "cron")
    items = cast(list[dict[str, object]], cron["items"])
    assert items[0]["id"] == "cron-sentinel"
    assert items[0]["ui_state"] == "running"


def test_workbench_snapshot_hydrates_checkpoint_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin import checkpoints

    def base_snapshot(_session: object) -> dict[str, object]:
        return {
            "header": {},
            "sessions": [],
            "agents": [],
            "cron": [],
            "errors": {},
        }

    def checkpoint_rows(
        _manager: object,
        _workspace: object,
    ) -> list[dict[str, str]]:
        return [{"hash": "a1b2c3d4", "summary": "Before QA"}]

    monkeypatch.setattr(dash, "snapshot", base_snapshot)
    monkeypatch.setattr(
        checkpoints.CheckpointManager,
        "list_checkpoints",
        checkpoint_rows,
    )
    session = types.SimpleNamespace(
        skills=types.SimpleNamespace(
            skills={
                "qa-skill": types.SimpleNamespace(name="qa-skill")
            }
        )
    )
    raw = cast(object, workbench.snapshot(session))
    assert isinstance(raw, dict)
    snapshot = cast(dict[str, object], raw)
    assert snapshot["checkpoints"] == [
        {"hash": "a1b2c3d4", "summary": "Before QA"}
    ]
    errors = cast(dict[str, object], snapshot["errors"])
    assert "복원" not in errors
    assert snapshot["zones"] == [
        {
            "id": "qa-skill",
            "name": "qa-skill",
            "status": "available",
        }
    ]


def test_default_chat_runs_the_unified_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object] | None] = []

    def run_workspace(
        cfg: dict[str, object] | None,
        _runner: workspace_terminal.LegacyRunner,
    ) -> int:
        calls.append(cfg)
        return 17

    def fake_run(
        cfg: dict[str, object] | None,
        runner: workspace_terminal.LegacyRunner,
    ) -> int:
        return run_workspace(cfg, runner)

    monkeypatch.setattr(workspace_terminal, "run", fake_run)

    def legacy_session(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("default chat entered the legacy REPL loop")

    monkeypatch.setattr(repl, "build_session", legacy_session)

    assert repl.run({"model": "fixture"}) == 17
    assert calls == [{"model": "fixture"}]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConfigError("invalid config"), 1),
        (RuntimeError("runtime failed"), None),
    ],
)
def test_terminal_closes_embedded_server_on_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected: int | None,
) -> None:
    class Background:
        bootstrap_url: str = "http://127.0.0.1:1/_bootstrap/test"
        closed: bool = False

        def close(self) -> None:
            self.closed = True

    background = Background()

    def start_background(_port: int | None) -> Background:
        return background

    monkeypatch.setattr(
        web_server,
        "start_background",
        start_background,
    )

    def fail_runtime(_session_id: str) -> object:
        raise error

    monkeypatch.setattr(web_server, "workspace_runtime", fail_runtime)

    def legacy_runner(
        _cfg: dict[str, object] | None,
        _session: Session,
        _turn_handler: workspace_terminal.TurnHandler,
    ) -> int:
        return 0

    if expected is None:
        with pytest.raises(type(error), match=str(error)):
            _ = workspace_terminal.run(None, legacy_runner)
    else:
        assert workspace_terminal.run(None, legacy_runner) == expected
    assert background.closed is True


@pytest.mark.parametrize(
    ("command", "panel", "notice"),
    [
        ("/work", "tasks_runs", "workbench"),
        ("/dash", "activity_logs", "deprecated"),
    ],
)
def test_legacy_terminal_aliases_focus_workspace(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    panel: str,
    notice: str,
) -> None:
    focused: list[str] = []

    def focus(key: str) -> None:
        focused.append(key)

    session = types.SimpleNamespace(
        workspace_focus=focus,
    )

    def independent_loop(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("legacy alias started an independent state loop")

    monkeypatch.setattr(workbench, "run", independent_loop)
    monkeypatch.setattr(dash, "run", independent_loop)

    assert slashcommands.dispatch(session, command) == "continue"
    assert focused == [panel]
    assert notice in capsys.readouterr().out.lower()


def test_terminal_render_keeps_chat_primary_at_every_width() -> None:
    workspace = importlib.import_module("birkin.workspace")
    render = getattr(workspace, "render_terminal", None)
    assert callable(render), "shared terminal workspace renderer is missing"
    renderer = cast(
        Callable[
            [Mapping[str, object], Mapping[str, object], tuple[int, int]],
            tuple[str, ...],
        ],
        render,
    )

    panels: list[dict[str, object]] = [
        {
            "key": key,
            "label": key,
            "items": (
                [
                    {
                        "id": "approval-1",
                        "summary": "Approve workspace action",
                        "ui_state": "action_needed",
                    }
                ]
                if key == "approvals"
                else []
            ),
        }
        for key in EXPECTED_PANEL_KEYS
    ]
    snapshot: dict[str, object] = {
        "conversation": [
            {
                "id": "message-1",
                "kind": "user_message",
                "text": "terminal-chat-sentinel 한글",
            }
        ],
        "composer": {"draft": "paste-sentinel 붙여넣기", "can_send": True},
        "panels": panels,
        "status": {"connection": "connected"},
    }
    view: dict[str, object] = {
        "active_panel": "approvals",
        "selected_item_id": None,
        "scroll_anchor": "message-1",
    }

    for size in ((60, 20), (100, 30), (160, 40)):
        lines = renderer(snapshot, view, size)
        text = "\n".join(lines)
        assert "terminal-chat-sentinel 한글" in text
        assert "paste-sentinel 붙여넣기" in text
        assert "◆ action · Approve workspace action" in text
        assert all(cell_width(line) <= size[0] for line in lines)
        if size[0] < 80:
            assert "Attention Queue" in text
        elif size[0] < 120:
            assert "Bench · Conversation" in text
        else:
            assert "Ledger (34) │ Bench" in text


def test_terminal_turn_routes_through_shared_workspace_session(
    tmp_path: Path,
) -> None:
    def factory(
        _session_id: str,
        emit: Callable[[str, dict[str, object]], WorkspaceEvent],
    ) -> dict[str, Callable[[dict[str, object]], dict[str, object]]]:
        def chat(payload: dict[str, object]) -> dict[str, object]:
            text = str(payload["text"])
            _ = emit("message.user", {"text": text})
            _ = emit("message.assistant.delta", {"text": "shared "})
            _ = emit("message.assistant.delta", {"text": "reply"})
            _ = emit(
                "message.assistant.completed",
                {"text": "shared reply"},
            )
            return {"reply": "shared reply"}

        return {"chat.send": chat}

    hub = WorkspaceHub(root=tmp_path, handler_factory=factory)
    session, _ = hub.create("terminal-shared")
    try:
        client = workspace_terminal.WorkspaceTerminalClient(
            session,
            actor_id="terminal:fixture",
        )
        pieces: list[str] = []
        reply = client.ask("hello", pieces.append)
    finally:
        hub.close()

    assert pieces == ["shared ", "reply"]
    assert reply == "shared reply"
    events = session.events(after=0)
    assert {event.actor_id for event in events} == {"terminal:fixture"}
    assert any(event.type == "message.user" for event in events)
    assert any(event.type == "message.assistant.completed" for event in events)
