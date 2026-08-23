from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from birkin.native import private_storage

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows ACL contract",
)


def test_windows_private_paths_receive_owner_only_acl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "authority"
    file = directory / "bootstrap.json"
    directory.mkdir()
    _ = file.write_text("secret", encoding="utf-8")
    calls: list[list[str]] = []

    def run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        stdout = (
            b'"runner","S-1-5-21-1000"\n'
            if command[0].endswith("whoami.exe")
            else b""
        )
        return subprocess.CompletedProcess(command, 0, stdout, b"")

    monkeypatch.setenv("SystemRoot", "C:/Windows")
    monkeypatch.setattr(private_storage.subprocess, "run", run)

    private_storage.harden_private_directory(directory)
    private_storage.harden_private_file(file)

    system = Path("C:/Windows") / "System32"
    assert calls == [
        [
            str(system / "whoami.exe"),
            "/user",
            "/fo",
            "csv",
            "/nh",
        ],
        [
            str(system / "icacls.exe"),
            str(directory),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-21-1000:(OI)(CI)F",
        ],
        [
            str(system / "whoami.exe"),
            "/user",
            "/fo",
            "csv",
            "/nh",
        ],
        [
            str(system / "icacls.exe"),
            str(file),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-21-1000:F",
        ],
    ]


def test_windows_private_path_fails_closed_without_security_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "bootstrap.json"
    _ = path.write_text("secret", encoding="utf-8")
    monkeypatch.delenv("SystemRoot", raising=False)

    with pytest.raises(OSError, match="Windows security tools"):
        private_storage.harden_private_file(path)
