"""Deterministic pexpect driver for terminal workspace evidence."""

from __future__ import annotations

import io
from pathlib import Path

import pexpect

from script.qa.workspace_handoff_support import (
    resize_terminal,
    send_terminal,
    spawn_terminal,
    stop_terminal,
)

PROMPT_READY = "\x1b[>1u"


def _prompt(child: pexpect.spawn[str]) -> None:
    _ = child.expect_exact(PROMPT_READY)


def run_terminal_scenario(profile: Path) -> dict[str, object]:
    complete = io.StringIO()
    child, _url, port = spawn_terminal(profile, complete)
    pid = child.pid
    captures: dict[int, str] = {}
    _prompt(child)

    send_terminal(child, "approval start")
    _ = child.expect_exact("fixture-tool")
    _ = child.expect_exact("Approval required. Type approve to resume.")
    _prompt(child)

    resize_terminal(child, 24, 60)
    width_60 = io.StringIO()
    child.logfile_read = width_60
    send_terminal(child, "/work")
    _ = child.expect_exact("focused tasks/runs.")
    _prompt(child)
    send_terminal(child, "approve")
    _ = child.expect_exact("shared continuation")
    _prompt(child)
    captures[60] = width_60.getvalue()
    _ = complete.write(captures[60])

    resize_terminal(child, 42, 160)
    width_160 = io.StringIO()
    child.logfile_read = width_160
    send_terminal(
        child,
        "붙여넣기-가나다라마바사가나다라마바사가나다라마바사-END",
    )
    _ = child.expect_exact("-END")
    _prompt(child)
    captures[160] = width_160.getvalue()
    _ = complete.write(captures[160])

    resize_terminal(child, 30, 100)
    width_100 = io.StringIO()
    child.logfile_read = width_100
    send_terminal(child, "interrupt")
    _ = child.expect_exact("interrupt-ready")
    _ = child.send("\x1b")
    _ = child.expect_exact("Interrupted safely")
    _prompt(child)
    send_terminal(child, "/dash")
    _ = child.expect_exact("deprecated")
    _prompt(child)
    captures[100] = width_100.getvalue()
    _ = complete.write(captures[100])
    stop_terminal(child)

    reconnect_log = io.StringIO()
    reconnect, _url, reconnect_port = spawn_terminal(profile, reconnect_log)
    if reconnect_port == port:
        raise AssertionError("reconnect reused a closed authority port")
    reconnect_pid = reconnect.pid
    _ = reconnect.expect_exact(
        "붙여넣기-가나다라마바사가나다라마바사가나다라마바사-END"
    )
    _prompt(reconnect)
    stop_terminal(reconnect)
    return {
        "first": complete.getvalue(),
        "reconnect": reconnect_log.getvalue(),
        "captures": captures,
        "pid": pid,
        "reconnect_pid": reconnect_pid,
        "port": port,
    }
