from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path
from typing import cast

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


def _windows_access_rules(path: Path) -> dict[str, object]:
    escaped = str(path).replace("'", "''")
    powershell = Path(os.environ["SystemRoot"]) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    result = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-Command",
            (
                f"$acl = [System.IO.File]::GetAccessControl('{escaped}'); "
                "$rules = @($acl.Access | ForEach-Object { "
                "[PSCustomObject]@{"
                "sid=$_.IdentityReference.Translate("
                "[System.Security.Principal.SecurityIdentifier]).Value;"
                "rights=[int]$_.FileSystemRights;"
                "type=[int]$_.AccessControlType;"
                "inherited=$_.IsInherited"
                "} }); "
                "[PSCustomObject]@{"
                "protected=$acl.AreAccessRulesProtected;"
                "rules=$rules"
                "} | ConvertTo-Json -Compress -Depth 3"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    decoded = cast(object, json.loads(result.stdout))
    assert isinstance(decoded, dict)
    mapping = cast(dict[object, object], decoded)
    assert all(isinstance(key, str) for key in mapping)
    return cast(dict[str, object], mapping)


def _assert_windows_owner_only(path: Path, *, sid: str) -> None:
    assert _windows_access_rules(path) == {
        "protected": True,
        "rules": [
            {
                "sid": sid,
                "rights": 2032127,
                "type": 0,
                "inherited": False,
            }
        ],
    }


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
    _assert_windows_owner_only(path, sid=sid)


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
        _assert_windows_owner_only(published, sid=sid)
    finally:
        path.unlink(missing_ok=True)
        published.unlink(missing_ok=True)


@_WINDOWS_ONLY
def test_windows_private_temp_closes_handle_when_fd_transfer_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    get_handle_information = ctypes.windll.kernel32.GetHandleInformation
    get_handle_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_handle_information.restype = wintypes.BOOL
    transferred_handles: list[int] = []

    def fail_transfer(handle: int, _flags: int) -> int:
        transferred_handles.append(handle)
        raise OSError("sentinel transfer failure")

    monkeypatch.setattr(msvcrt, "open_osfhandle", fail_transfer)

    with pytest.raises(OSError, match="sentinel transfer failure"):
        _ = private_storage.create_private_temp(
            tmp_path,
            prefix=".bootstrap.",
        )

    assert len(transferred_handles) == 1
    flags = wintypes.DWORD()
    assert not get_handle_information(
        wintypes.HANDLE(transferred_handles[0]),
        ctypes.byref(flags),
    )
    assert list(tmp_path.iterdir()) == []


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
