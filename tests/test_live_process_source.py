"""Tests for the injectable live-process source adapters."""

from __future__ import annotations

import os
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from birkin import live_process_source, operation_policy
from birkin.live_process_source import (
    ProcessHandle,
    ProcessSource,
    PsutilProcessHandle,
    PsutilProcessSource,
)


class _FakePsutilProcess:
    def __init__(
        self,
        *,
        pid: int = 4312,
        username: str = "DOMAIN\\lg",
        name: str = "codex.exe",
        cmdline: tuple[str, ...] = ("codex.exe", "exec"),
        cwd: str = r"C:\workspace",
        open_files: tuple[str, ...] = (),
    ) -> None:
        self.pid = pid
        self._username = username
        self._name = name
        self._cmdline = cmdline
        self._cwd = cwd
        self._open_files = open_files

    def username(self) -> str:
        return self._username

    def name(self) -> str:
        return self._name

    def cmdline(self) -> list[str]:
        return list(self._cmdline)

    def cwd(self) -> str:
        return self._cwd

    def open_files(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(path=path) for path in self._open_files]


def test_psutil_process_handle_satisfies_protocol_and_adapts_fields() -> None:
    command = (
        "codex.exe",
        "exec",
        "argument with spaces",
        "unique-final-token",
    )
    process = _FakePsutilProcess(
        cmdline=command,
        open_files=(r"C:\sessions\one.jsonl", r"C:\sessions\two.jsonl"),
    )
    handle = PsutilProcessHandle(process)
    expected_command = (
        subprocess.list2cmdline(command)
        if os.name == "nt"
        else shlex.join(command)
    )

    assert isinstance(handle, ProcessHandle)
    assert callable(handle.pid)
    assert handle.username() == "DOMAIN\\lg"
    assert handle.pid() == 4312
    assert handle.name() == "codex.exe"
    assert handle.cmdline() == expected_command
    assert handle.cmdline().endswith("unique-final-token")
    assert handle.cwd() == r"C:\workspace"
    assert handle.open_files() == (
        r"C:\sessions\one.jsonl",
        r"C:\sessions\two.jsonl",
    )


def test_psutil_process_source_satisfies_protocol_without_eager_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _FakePsutilProcess(username="DOMAIN\\current")
    listed = (_FakePsutilProcess(pid=10), _FakePsutilProcess(pid=20))
    process_iter_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def process_iter(
        *args: object,
        **kwargs: object,
    ) -> tuple[_FakePsutilProcess, ...]:
        process_iter_calls.append((args, kwargs))
        return listed

    monkeypatch.setattr(live_process_source.psutil, "Process", lambda: current)
    monkeypatch.setattr(live_process_source.psutil, "process_iter", process_iter)
    source = PsutilProcessSource()

    assert isinstance(source, ProcessSource)
    assert source.current_username() == "DOMAIN\\current"
    handles = tuple(source.processes())
    assert [handle.pid() for handle in handles] == [10, 20]
    assert process_iter_calls == [((), {})]


@pytest.mark.parametrize("marker", operation_policy._PERMISSION_MARKERS)
def test_permission_denial_helper_preserves_existing_markers(
    marker: str,
) -> None:
    assert operation_policy.is_permission_denial(
        f"native failure: {marker.upper()}"
    )


def test_permission_denial_helper_rejects_unrelated_errors() -> None:
    assert not operation_policy.is_permission_denial(
        "the process disappeared before inspection"
    )


def test_permission_denial_summary_is_canonical() -> None:
    assert operation_policy.permission_denial_summary() == "access is denied"
