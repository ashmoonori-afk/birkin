from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from birkin.workspace.contracts import ProtocolError
from birkin.workspace.terminal_policy import (
    ApprovedTerminalLaunch,
    TerminalIdentity,
    TerminalInputIntent,
)
from birkin.workspace.terminal_session import TerminalSessions
from tests.test_terminal_output_runtime import EventProcess, process_factory
from tests.test_terminal_redaction import CARET_COMMANDS, DYNAMIC_ONLY_COMMANDS


@pytest.mark.parametrize(
    "command",
    [
        b"echo prefix & set PASSWORD=secret\r\n",
        b"echo prefix && set PASSWORD=secret\r\n",
        b"echo prefix || set PASSWORD=secret\r\n",
        b"echo prefix\r\nset PASSWORD=secret\r\n",
        b"cmd /c set PASSWORD=secret\r\n",
        b"call set PASSWORD=secret\r\n",
        b'echo prefix & set "PASSWORD=secret"\r\n',
        b"set harmless=ok & set PASSWORD=secret\r\n",
        b"set harmless=ok && set TOKEN=secret && set other=ok\r\n",
        b"set PASSWORD=secret & set harmless=ok\r\n",
        b'set "harmless=ok" || set "MY_DB_PASSWORD=secret"\r\n',
        b"set one=ok\r\nset two=ok\r\ncall set AUTHORIZATION=secret\r\n",
        b"echo %PATH% & set PASSWORD=STATIC_SECRET\r\n",
        b"set PASSWORD=STATIC_SECRET & echo %PATH%\r\n",
        b"echo %LEFT% && set TOKEN=STATIC_SECRET && echo !RIGHT!\r\n",
        b"se^t PASSWORD=STATIC_SECRET & echo %PATH%\r\n",
        b"echo !LEFT! || s^et SECRET=STATIC_SECRET || echo %RIGHT%\r\n",
        b"echo %0 & set PASSWORD=STATIC_SECRET & echo %PATH%\r\n",
        b"echo %x & se^t TOKEN=STATIC_SECRET & echo !NEXT!\r\n",
        b"echo %*%PATH% & set SECRET=STATIC_SECRET\r\n",
        b"echo %0%PATH%!NEXT!%1 & set PASSWORD=STATIC_SECRET\r\n",
        b"echo %_unclosed & set PASSWORD=STATIC_SECRET\r\n",
        b"echo !unclosed & se^t TOKEN=STATIC_SECRET\r\n",
    ],
)
def test_embedded_sensitive_assignment_is_rejected_before_process_write(
    tmp_path: Path,
    command: bytes,
) -> None:
    # Given a live terminal and unsupported embedded sensitive assignment
    process = EventProcess()
    sessions = TerminalSessions(
        "session-1",
        lambda kind, payload: payload,
        process_factory(process),
    )
    opened = sessions.create(
        ApprovedTerminalLaunch(Path("cmd.exe"), tmp_path, {}, "approval")
    )
    identity = TerminalIdentity(str(opened["terminal_id"]), str(opened["lease"]))
    try:
        # When the assignment crosses the final boundary, Then no byte is written
        with pytest.raises(ProtocolError, match="sensitive terminal assignment"):
            _ = sessions.input(TerminalInputIntent(identity, 1, command))
        assert process.writes == []
    finally:
        sessions.close_all()



@pytest.mark.parametrize(
    "command",
    CARET_COMMANDS
    + (
        b"echo ok && se^t TOKEN=secret\r\n",
    ),
)
def test_obfuscated_assignment_has_zero_process_writes(
    tmp_path: Path,
    command: bytes,
) -> None:
    process = EventProcess()
    sessions = TerminalSessions(
        "session-1",
        lambda kind, payload: payload,
        process_factory(process),
    )
    opened = sessions.create(
        ApprovedTerminalLaunch(Path("cmd.exe"), tmp_path, {}, "approval")
    )
    identity = TerminalIdentity(str(opened["terminal_id"]), str(opened["lease"]))
    try:
        with pytest.raises(ProtocolError, match="sensitive terminal assignment"):
            _ = sessions.input(TerminalInputIntent(identity, 1, command))
        assert process.writes == []
    finally:
        sessions.close_all()


@pytest.mark.parametrize("command", DYNAMIC_ONLY_COMMANDS)
def test_dynamic_expansion_writes_exactly_without_guessed_registration(
    tmp_path: Path,
    command: bytes,
) -> None:
    process = EventProcess()
    output_ready = threading.Event()
    outputs: list[str] = []

    def emit(kind: str, payload: dict[str, object]) -> object:
        if kind == "terminal.output":
            outputs.append(str(payload["data"]))
            output_ready.set()
        return payload

    sessions = TerminalSessions("session-1", emit, process_factory(process))
    opened = sessions.create(
        ApprovedTerminalLaunch(Path("cmd.exe"), tmp_path, {}, "approval")
    )
    identity = TerminalIdentity(str(opened["terminal_id"]), str(opened["lease"]))
    try:
        _ = sessions.input(TerminalInputIntent(identity, 1, command))
        assert process.writes == [command]
        process.publish(b"DYNAMIC_VISIBLE")
        assert output_ready.wait(2.0)
        assert "DYNAMIC_VISIBLE" in "".join(outputs)
    finally:
        sessions.close_all()


@pytest.mark.skipif(sys.platform != "win32", reason="real cmd caret semantics")
@pytest.mark.parametrize(
    ("assignment", "key"),
    [
        ("s^et PASSWORD=probe", "PASSWORD"),
        ("set PASS^WORD=probe", "PASSWORD"),
        ("se^t TO^KEN=probe", "TOKEN"),
        ("set PASSWORD^=probe", "PASSWORD"),
    ],
)
def test_native_cmd_caret_assignment_creates_canonical_environment_key(
    assignment: str,
    key: str,
) -> None:
    # Given a representative caret-obfuscated assignment submitted to real cmd
    command = Path(os.environ["ComSpec"])
    result = subprocess.run(
        [str(command), "/d", "/q", "/c", f"setlocal & {assignment} & set {key}"],
        capture_output=True,
        text=True,
        check=False,
    )
    # Then cmd creates the canonical key that detection must protect
    assert result.returncode == 0
    assert f"{key}=probe" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="real cmd expansion semantics")
@pytest.mark.parametrize(
    ("name", "delimiters", "delayed"),
    [
        ("frag_name", "%", False),
        ("frag.name", "%", False),
        ("frag-name", "%", False),
        ("frag_name", "!", True),
    ],
)
def test_native_cmd_dynamic_keyword_creates_sensitive_environment_key(
    name: str,
    delimiters: str,
    delayed: bool,
) -> None:
    command = Path(os.environ["ComSpec"])
    expansion = f"{delimiters}{name}{delimiters}"
    result = subprocess.run(
        [
            str(command),
            "/d",
            "/q",
            "/v:on" if delayed else "/v:off",
            "/c",
            f"s{expansion}t PASSWORD=probe & set PASSWORD",
        ],
        capture_output=True,
        env={**os.environ, name: "e"},
        check=False,
    )
    assert result.returncode == 0
    assert b"PASSWORD=probe" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        b'set harmless=ok & set "arbitrary=VISIBLE"\r\n',
        b"echo PASS^WORD=literal\r\n",
        b"echo s^et literal\r\n",
        b"echo %PATH% !TIME!\r\n",
        b"echo %frag_name% !frag.name!\r\n",
        b"echo %with space% !mix_1.- $!\r\n",
    ],
)
def test_benign_command_writes_exact_bytes(tmp_path: Path, command: bytes) -> None:
    # Given a benign command that detection may canonicalize internally
    process = EventProcess()
    sessions = TerminalSessions(
        "session-1",
        lambda kind, payload: payload,
        process_factory(process),
    )
    opened = sessions.create(
        ApprovedTerminalLaunch(Path("cmd.exe"), tmp_path, {}, "approval")
    )
    identity = TerminalIdentity(str(opened["terminal_id"]), str(opened["lease"]))
    try:
        # When it crosses the input boundary, Then bytes remain exact
        _ = sessions.input(TerminalInputIntent(identity, 1, command))
        assert process.writes == [command]
    finally:
        sessions.close_all()
