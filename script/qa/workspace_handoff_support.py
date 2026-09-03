"""Typed PTY and snapshot helpers for cross-surface workspace QA."""

from __future__ import annotations

import io
import hashlib
import json
import os
import re
import struct
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, cast, final

import pexpect
from playwright.sync_api import Page

from script.qa.workspace_conpty import ConptySpawn
from script.qa.workspace_terminal_protocol import TerminalProcess

if TYPE_CHECKING:
    from pexpect.pty_spawn import spawn as PexpectSpawn


@final
class _PexpectTerminal:
    def __init__(self, process: PexpectSpawn[str]) -> None:
        self._process = process

    @property
    def pid(self) -> int | None:
        return self._process.pid

    @property
    def exitstatus(self) -> int | None:
        return self._process.exitstatus

    def set_logfile_read(self, logfile: TextIO | None) -> None:
        self._process.logfile_read = logfile

    def matched_group(self, index: int) -> str:
        match self._process.match:
            case re.Match() as matched:
                return matched.group(index)
            case _:
                raise AssertionError("pexpect has no regular-expression match")

    def send(self, value: str) -> int:
        return self._process.send(value)

    def setwinsize(self, rows: int, columns: int) -> None:
        resize: Callable[[int, int], None] = self._process.setwinsize
        resize(rows, columns)

    def expect_exact(self, pattern: str, timeout: float | None = None) -> int:
        return self._process.expect_exact(pattern, timeout=timeout)

    def expect(self, pattern: str, timeout: float | None = None) -> int:
        return self._process.expect(pattern, timeout=timeout)

    def expect_eof(self, timeout: float | None = None) -> None:
        _ = self._process.expect(pexpect.EOF, timeout=timeout)

    def terminate(self, force: bool = False) -> bool:
        return self._process.terminate(force=force)

    def close(self, force: bool = False) -> None:
        self._process.close(force=force)

    def isalive(self) -> bool:
        return self._process.isalive()


ROOT = Path(__file__).resolve().parents[2]


def send_terminal(child: TerminalProcess, text: str) -> None:
    _ = child.send(text + "\r")


def resize_terminal(
    child: TerminalProcess,
    rows: int,
    columns: int,
) -> None:
    child.setwinsize(rows, columns)


def workspace_snapshot(page: Page) -> dict[str, object]:
    payload = cast(
        object,
        page.evaluate(
            """async () => {
              const session = localStorage.getItem('birkin.workspace.session');
              const response = await fetch(
                `/api/workspace/sessions/${session}/snapshot`
              );
              return response.json();
            }"""
        ),
    )
    if not isinstance(payload, dict):
        raise TypeError("handoff snapshot must be an object")
    return cast(dict[str, object], payload)


def history_hash(snapshot: dict[str, object]) -> str:
    conversation = snapshot.get("conversation")
    encoded = json.dumps(
        conversation,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def replay_duplicate_command(page: Page, text: str) -> dict[str, object]:
    result = cast(
        object,
        page.evaluate(
            """async (text) => {
              const session = localStorage.getItem('birkin.workspace.session');
              const snapshot = await (
                await fetch(`/api/workspace/sessions/${session}/snapshot`)
              ).json();
              const body = {
                protocol_version: 1,
                command_id: "qa-cross-surface-duplicate",
                expected_cursor: snapshot.cursor,
                type: "chat.send",
                payload: {text},
                client_context: {surface: "web", view_id: "browser-duplicate"},
              };
              const path = `/api/workspace/sessions/${session}/commands`;
              const first = await fetch(path, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(body),
              });
              const second = await fetch(path, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(body),
              });
              return {
                firstStatus: first.status,
                secondStatus: second.status,
                first: await first.json(),
                second: await second.json(),
              };
            }""",
            text,
        ),
    )
    if not isinstance(result, dict):
        raise TypeError("duplicate command result must be an object")
    return cast(dict[str, object], result)


def workspace_events(page: Page) -> list[dict[str, object]]:
    result = cast(
        object,
        page.evaluate(
            """async () => {
              const session = localStorage.getItem('birkin.workspace.session');
              const text = await (
                await fetch(
                  `/api/workspace/sessions/${session}/events?after=0&once=1`
                )
              ).text();
              return text.split("\\n")
                .filter((line) => line.startsWith("data: "))
                .map((line) => JSON.parse(line.slice(6)));
            }"""
        ),
    )
    if not isinstance(result, list):
        raise TypeError("workspace events must be a list")
    return cast(list[dict[str, object]], result)


def spawn_terminal(
    profile: Path,
    terminal_log: io.StringIO,
) -> tuple[TerminalProcess, str, int]:
    env = os.environ.copy()
    env["BIRKIN_HOME"] = str(profile)
    child: TerminalProcess
    if sys.platform == "win32":
        child = ConptySpawn.spawn(
            sys.executable,
            ["-m", "script.qa.workspace_terminal_fixture"],
            cwd=str(ROOT),
            env=env,
            encoding="utf-8",
            timeout=30,
            dimensions=(30, 100),
        )
    else:
        from pexpect.pty_spawn import spawn as PexpectSpawnRuntime

        child = _PexpectTerminal(PexpectSpawnRuntime(
            sys.executable,
            ["-m", "script.qa.workspace_terminal_fixture"],
            cwd=str(ROOT),
            env=env,
            encoding="utf-8",
            timeout=30,
            dimensions=(30, 100),
        ))
    child.set_logfile_read(terminal_log)
    _ = child.expect(r"web workspace: (\S+)")
    url = child.matched_group(1)
    port_match = re.search(r":(\d+)/", url)
    if port_match is None:
        raise AssertionError("handoff URL did not contain a port")
    return child, url, int(port_match.group(1))


def stop_terminal(child: TerminalProcess) -> int:
    send_terminal(child, "/quit")
    _ = child.expect_exact("bye.")
    child.expect_eof()
    _ = child.close()
    if child.exitstatus != 0:
        raise AssertionError(f"terminal fixture exited {child.exitstatus}")
    return child.exitstatus


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("handoff capture is not a PNG")
    return struct.unpack(">II", data[16:24])
