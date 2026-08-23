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
            b'"S-1-5-32-545","S-1-5-21-1000"\n'
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
            "/reset",
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
            "/reset",
        ],
        [
            str(system / "icacls.exe"),
            str(file),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-21-1000:F",
        ],
    ]


def test_windows_private_file_removes_explicit_everyone_ace(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bootstrap.json"
    _ = path.write_text("secret", encoding="utf-8")
    system = Path(os.environ["SystemRoot"]) / "System32"
    subprocess.run(
        [
            str(system / "icacls.exe"),
            str(path),
            "/grant",
            "*S-1-1-0:F",
        ],
        check=True,
        capture_output=True,
    )

    private_storage.harden_private_file(path)

    escaped = str(path).replace("'", "''")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"(Get-Acl -LiteralPath '{escaped}').Sddl",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert ";;;WD)" not in result.stdout


def test_windows_private_temp_is_owner_only_at_creation(
    tmp_path: Path,
) -> None:
    descriptor, name = private_storage.create_private_temp(
        tmp_path,
        prefix=".bootstrap.",
    )
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            _ = handle.write("secret")
        escaped = str(path).replace("'", "''")
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"(Get-Acl -LiteralPath '{escaped}').Sddl",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert ";;;WD)" not in result.stdout
        assert ":P(" in result.stdout
    finally:
        path.unlink(missing_ok=True)


def test_windows_private_path_fails_closed_without_security_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "bootstrap.json"
    _ = path.write_text("secret", encoding="utf-8")
    monkeypatch.delenv("SystemRoot", raising=False)

    with pytest.raises(OSError, match="Windows security tools"):
        private_storage.harden_private_file(path)
