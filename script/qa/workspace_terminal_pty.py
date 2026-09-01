"""Deterministic shared driver for portable terminal workspace evidence."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pexpect

from script.qa.workspace_handoff_support import (
    resize_terminal,
    send_terminal,
    spawn_terminal,
    stop_terminal,
)

PROMPT_READY = "\x1b[>1u"


@dataclass(frozen=True, slots=True)
class TerminalCapture:
    width: int
    raw: str


@dataclass(frozen=True, slots=True)
class ChildExit:
    pid: int
    exit_code: int | None


@dataclass(frozen=True, slots=True)
class TerminalScenario:
    transcript: str
    captures: tuple[TerminalCapture, ...]
    children: tuple[ChildExit, ...]
    first_port: int
    reconnect_port: int


def _prompt(child: pexpect.spawn[str]) -> None:
    _ = child.expect_exact(PROMPT_READY)


def _capture(
    child: pexpect.spawn[str],
    complete: io.StringIO,
    *,
    rows: int,
    columns: int,
    action: str,
    sentinel: str,
) -> TerminalCapture:
    resize_terminal(child, rows, columns)
    output = io.StringIO()
    child.logfile_read = output
    send_terminal(child, action)
    _ = child.expect_exact(sentinel)
    _prompt(child)
    raw = output.getvalue()
    _ = complete.write(raw)
    return TerminalCapture(width=columns, raw=raw)


def run_terminal_scenario(profile: Path) -> TerminalScenario:
    """Run one approval, work, Unicode, interrupt, quit, and reconnect story."""
    complete = io.StringIO()
    child, _url, first_port = spawn_terminal(profile, complete)
    if child.pid is None:
        raise AssertionError("terminal child process identifier missing")
    first_pid = child.pid
    try:
        _prompt(child)
        send_terminal(child, "approval start")
        _ = child.expect_exact("fixture-tool")
        _ = child.expect_exact("Approval required. Type approve to resume.")
        _prompt(child)

        capture_60 = _capture(
            child,
            complete,
            rows=24,
            columns=60,
            action="/work",
            sentinel="focused tasks/runs.",
        )
        send_terminal(child, "approve")
        _ = child.expect_exact("shared continuation")
        _prompt(child)

        capture_80 = _capture(
            child,
            complete,
            rows=26,
            columns=80,
            action="/work",
            sentinel="focused tasks/runs.",
        )
        capture_160 = _capture(
            child,
            complete,
            rows=42,
            columns=160,
            action="붙여넣기-가나다라마바사가나다라마바사가나다라마바사-END",
            sentinel="-END",
        )
        capture_120 = _capture(
            child,
            complete,
            rows=34,
            columns=120,
            action="/work",
            sentinel="focused tasks/runs.",
        )

        resize_terminal(child, 30, 100)
        output_100 = io.StringIO()
        child.logfile_read = output_100
        send_terminal(child, "interrupt")
        _ = child.expect_exact("interrupt-ready")
        _ = child.send("\x1b")
        _ = child.expect_exact("Interrupted safely")
        _prompt(child)
        raw_100 = output_100.getvalue()
        _ = complete.write(raw_100)
        capture_100 = TerminalCapture(width=100, raw=raw_100)
        first_exit = stop_terminal(child)
    finally:
        if child.isalive():
            child.close(force=True)

    reconnect_log = io.StringIO()
    reconnect, _url, reconnect_port = spawn_terminal(profile, reconnect_log)
    if reconnect.pid is None:
        raise AssertionError("reconnect child process identifier missing")
    reconnect_pid = reconnect.pid
    try:
        if reconnect_port == first_port:
            raise AssertionError("reconnect reused a closed authority port")
        _ = reconnect.expect_exact(
            "붙여넣기-가나다라마바사가나다라마바사가나다라마바사-END"
        )
        _prompt(reconnect)
        reconnect_exit = stop_terminal(reconnect)
    finally:
        if reconnect.isalive():
            reconnect.close(force=True)

    reconnect_text = reconnect_log.getvalue()
    return TerminalScenario(
        transcript=complete.getvalue() + "\n--- RECONNECT ---\n" + reconnect_text,
        captures=(capture_60, capture_80, capture_100, capture_120, capture_160),
        children=(
            ChildExit(pid=first_pid, exit_code=first_exit),
            ChildExit(pid=reconnect_pid, exit_code=reconnect_exit),
        ),
        first_port=first_port,
        reconnect_port=reconnect_port,
    )
