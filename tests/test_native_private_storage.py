from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path

import pytest

from birkin.native import private_storage

_WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt", reason="Windows ACL contract"
)


def _windows_owner_sid(system: Path) -> str:
    result = subprocess.run(
        [
            str(system / "whoami.exe"),
            "/user",
            "/fo",
            "csv",
            "/nh",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = list(csv.reader(result.stdout.splitlines()))
    assert len(rows) == 1
    return rows[0][-1]


def _windows_dacl(path: Path) -> str:
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
    _, separator, tail = result.stdout.strip().partition("D:")
    assert separator == "D:"
    return "D:" + tail.split("S:", 1)[0]


def test_windows_owner_sid_ignores_localized_username_bytes() -> None:
    output = (
        "사용자".encode("cp949")
        + b',"S-1-5-21-1000"\r\n'
    )

    assert private_storage._windows_owner_sid(output) == "S-1-5-21-1000"


@_WINDOWS_ONLY
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

    sid = _windows_owner_sid(system)
    assert _windows_dacl(path) == f"D:P(A;;FA;;;{sid})"


@_WINDOWS_ONLY
def test_windows_private_temp_is_owner_only_at_creation(
    tmp_path: Path,
) -> None:
    descriptor, name = private_storage.create_private_temp(
        tmp_path,
        prefix=".bootstrap.",
    )
    path = Path(name)
    published = tmp_path / "published-bootstrap.json"
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            _ = handle.write("secret")
        _ = published.write_text("old", encoding="utf-8")
        system = Path(os.environ["SystemRoot"]) / "System32"
        subprocess.run(
            [
                str(system / "icacls.exe"),
                str(published),
                "/grant",
                "*S-1-1-0:F",
            ],
            check=True,
            capture_output=True,
        )
        os.replace(path, published)
        sid = _windows_owner_sid(system)
        assert _windows_dacl(published) == f"D:P(A;;FA;;;{sid})"
    finally:
        path.unlink(missing_ok=True)
        published.unlink(missing_ok=True)


@_WINDOWS_ONLY
def test_windows_private_path_fails_closed_without_security_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "bootstrap.json"
    _ = path.write_text("secret", encoding="utf-8")
    monkeypatch.delenv("SystemRoot", raising=False)

    with pytest.raises(OSError, match="Windows security tools"):
        private_storage.harden_private_file(path)
