"""Default terminal entry point for the unified Birkin workspace."""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast, final

from . import ui, workbench
from .runtime import ConfigError, Session
from .workspace import WorkspaceCommand, WorkspaceSession, render_terminal
from .workspace.records import PANEL_KEYS
from .workspace.theme import DEFAULT_PALETTE, PALETTES


@dataclass
class TerminalWorkspaceState:
    active_panel: str = "tasks_runs"
    selected_item_id: str | None = None
    scroll_anchor: str | None = None

    def focus(self, panel: str) -> None:
        if panel in PANEL_KEYS:
            self.active_panel = panel

    def to_view(self) -> dict[str, object]:
        return {
            "active_panel": self.active_panel,
            "selected_item_id": self.selected_item_id,
            "scroll_anchor": self.scroll_anchor,
        }


@final
class WorkspaceTerminalClient:
    def __init__(
        self,
        session: WorkspaceSession,
        *,
        actor_id: str,
        on_event: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        self._session = session
        self._actor_id = actor_id
        self._on_event = on_event

    def ask(
        self,
        text: str,
        on_text: Callable[[str], None],
    ) -> str:
        cursor = self._session.snapshot().cursor
        command = WorkspaceCommand.parse(
            {
                "protocol_version": 1,
                "command_id": f"terminal-{uuid.uuid4()}",
                "expected_cursor": cursor,
                "type": "chat.send",
                "payload": {"text": text},
                "client_context": {
                    "surface": "terminal",
                    "view_id": "local",
                },
            }
        )
        receipt = self._session.submit(command, actor_id=self._actor_id)
        final = ""
        while True:
            events = self._session.wait_events(
                after=cursor,
                until=None,
                timeout=300,
            )
            if not events:
                raise TimeoutError("workspace turn produced no event")
            for event in events:
                cursor = max(cursor, event.cursor)
                if event.command_id != receipt.command_id:
                    continue
                if event.type == "message.assistant.delta":
                    piece = event.payload.get("text")
                    if isinstance(piece, str):
                        on_text(piece)
                elif event.type == "message.assistant.completed":
                    text_value = event.payload.get("text")
                    if isinstance(text_value, str):
                        final = text_value
                elif event.type == "command.failed":
                    raise RuntimeError(
                        str(event.payload.get("error") or "workspace command failed")
                    )
                elif event.type in {
                    "tool.started",
                    "tool.completed",
                    "tool.failed",
                    "progress.updated",
                    "approval.requested",
                    "question.requested",
                    "evidence.added",
                    "task.updated",
                } and self._on_event is not None:
                    runtime_event = event.payload.get("runtime_event")
                    event_name = (
                        runtime_event
                        if isinstance(runtime_event, str)
                        else event.type
                    )
                    self._on_event(event_name, event.payload)
                elif event.type == "command.completed":
                    return final


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, object], value)


def _messages(session: Session) -> list[dict[str, object]]:
    rendered: list[dict[str, object]] = []
    raw_messages: Sequence[object] = cast(Sequence[object], session.agent.messages)
    for index, raw in enumerate(raw_messages[-12:]):
        message = _mapping(raw)
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        rendered.append(
            {
                "id": f"message-{index}",
                "kind": (
                    "user_message" if role == "user" else "assistant_message"
                ),
                "text": content,
            }
        )
    return rendered


def _panels(session: Session) -> list[dict[str, object]]:
    raw = workbench.snapshot(session)
    sources = {
        "tasks_runs": raw.get("agents", []),
        "approvals": raw.get("approvals", []),
        "files_evidence": raw.get("checkpoints", []),
        "sessions_history": raw.get("sessions", []),
        "activity_logs": raw.get("activity", []),
        "cron": raw.get("cron", []),
        "memory_skills": raw.get("zones", []),
        "checkpoints_restore": raw.get("checkpoints", []),
        "settings_status": [raw.get("header", {})],
    }
    return [
        {"key": key, "label": key, "items": sources[key]}
        for key in PANEL_KEYS
    ]


def snapshot(session: Session) -> dict[str, object]:
    if session.workspace_snapshot is not None:
        return session.workspace_snapshot().to_json()
    return {
        "conversation": _messages(session),
        "composer": {"draft": "", "can_send": True},
        "panels": _panels(session),
        "status": {"connection": "connected"},
    }


def render_session(
    session: Session,
    state: TerminalWorkspaceState,
) -> None:
    try:
        size = os.get_terminal_size(sys.stdin.fileno())
    except OSError:
        size = shutil.get_terminal_size((100, 30))
    palette = os.environ.get("BIRKIN_WORKSPACE_THEME", DEFAULT_PALETTE)
    if palette not in PALETTES:
        palette = DEFAULT_PALETTE
    forced_mode = os.environ.get("BIRKIN_COLOR_MODE")
    if "NO_COLOR" in os.environ or forced_mode == "none":
        color_mode = "none"
    elif forced_mode in {"truecolor", "ansi256"}:
        color_mode = forced_mode
    elif not sys.stdout.isatty() or os.environ.get("TERM") == "dumb":
        color_mode = "none"
    elif "256color" in os.environ.get("TERM", ""):
        color_mode = "ansi256"
    else:
        color_mode = "truecolor"
    lines = render_terminal(
        snapshot(session),
        state.to_view(),
        (size.columns, size.lines),
        color=color_mode != "none",
        ansi_256=color_mode == "ansi256",
        palette=palette,
    )
    print("\n".join(lines))


TurnHandler = Callable[[str, Callable[[str], None]], str]
LegacyRunner = Callable[[dict[str, object] | None, Session, TurnHandler], int]


def run(
    cfg: dict[str, object] | None,
    legacy_runner: LegacyRunner,
) -> int:
    from .web import server as web_server

    configured_port = (cfg or {}).get("web_port")
    port = (
        configured_port
        if isinstance(configured_port, int) and not isinstance(configured_port, bool)
        else None
    )
    background = web_server.start_background(port)
    try:
        session_id_value = (cfg or {}).get("session_id")
        session_id = (
            session_id_value
            if isinstance(session_id_value, str) and session_id_value
            else "default"
        )
        try:
            shared_session, runtime_session = web_server.workspace_runtime(
                session_id
            )
        except ConfigError as exc:
            print(f"{ui.RED}{exc}{ui.RESET}")
            return 1
        runtime_session.workspace_snapshot = (
            lambda: web_server.workspace_snapshot(session_id)
        )
        printer = ui.make_event_printer()
        client = WorkspaceTerminalClient(
            shared_session,
            actor_id="terminal:local",
            on_event=printer,
        )
        print(f" web workspace: {background.bootstrap_url}")
        return legacy_runner(cfg, runtime_session, client.ask)
    finally:
        background.close()
