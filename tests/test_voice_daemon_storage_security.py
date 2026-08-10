from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import IO

import pytest

from birkin.voice.daemon_state import DaemonState
from birkin.voice.daemon_storage import claim_state, load_state


def test_claim_state_is_not_visible_until_json_is_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.voice import daemon_storage

    state_path = tmp_path / "daemon.json"
    state = DaemonState(
        instance_id="instance-id",
        token="control-token",
        pid=4242,
        host="127.0.0.1",
        port=45454,
    )
    partial_written = threading.Event()
    release_write = threading.Event()
    dump = daemon_storage.json.dump

    def slow_dump(
        value: object,
        handle: IO[str],
        *,
        sort_keys: bool = False,
    ) -> None:
        handle.write("{")
        handle.flush()
        partial_written.set()
        assert release_write.wait(timeout=2.0)
        handle.seek(0)
        handle.truncate()
        dump(value, handle, sort_keys=sort_keys)

    monkeypatch.setattr(daemon_storage.json, "dump", slow_dump)
    writer = threading.Thread(target=claim_state, args=(state_path, state))
    writer.start()
    assert partial_written.wait(timeout=10.0)

    with pytest.raises(FileNotFoundError):
        load_state(state_path)

    release_write.set()
    writer.join(timeout=2.0)
    assert writer.is_alive() is False
    assert load_state(state_path) == state


def test_windows_acl_hardening_resets_foreign_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin.voice import daemon_storage

    commands: list[list[str]] = []

    def run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        creationflags: int,
    ) -> subprocess.CompletedProcess[bytes]:
        assert check is False
        assert capture_output is True
        assert creationflags >= 0
        commands.append(command)
        stdout = (
            b'"MOONDESK\\\\lg","S-1-5-21-1-2-3-1001"\r\n'
            if command[0].endswith("whoami.exe")
            else b""
        )
        return subprocess.CompletedProcess(command, 0, stdout, b"")

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(daemon_storage.subprocess, "run", run)

    daemon_storage._harden_windows_directory(tmp_path)

    assert commands == [
        [
            r"C:\Windows\System32\whoami.exe",
            "/user",
            "/fo",
            "csv",
            "/nh",
        ],
        [
            r"C:\Windows\System32\icacls.exe",
            str(tmp_path),
            "/reset",
        ],
        [
            r"C:\Windows\System32\icacls.exe",
            str(tmp_path),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-21-1-2-3-1001:(OI)(CI)F",
        ],
    ]
