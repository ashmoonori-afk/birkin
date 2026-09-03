"""Detached spawns must survive a job object that forbids breakaway."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from birkin import proc

_GROUP = 0x00000200
_BREAKAWAY = 0x01000000


def _access_denied() -> OSError:
    error = OSError(13, "Access is denied")
    error.winerror = 5  # pyright: ignore[reportAttributeAccessIssue]
    return error


def test_breakaway_denied_by_the_job_retries_without_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the parent runs inside a job without JOB_OBJECT_LIMIT_BREAKAWAY_OK.
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", _GROUP, raising=False)
    monkeypatch.setattr(
        subprocess,
        "CREATE_BREAKAWAY_FROM_JOB",
        _BREAKAWAY,
        raising=False,
    )
    attempts: list[dict[str, Any]] = []

    def fake_popen(_argv: list[str], **kwargs: Any) -> str:
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise _access_denied()
        return "spawned"

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    # When
    spawned = proc.popen_detached(["python", "-m", "birkin"], close_fds=True)

    # Then: the retry drops only the breakaway bit and keeps every other kwarg.
    assert spawned == "spawned"
    assert [attempt["creationflags"] for attempt in attempts] == [
        _GROUP | _BREAKAWAY,
        _GROUP,
    ]
    assert [attempt["close_fds"] for attempt in attempts] == [True, True]


def test_other_spawn_failures_are_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a failure that dropping the breakaway flag cannot fix.
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", _GROUP, raising=False)
    monkeypatch.setattr(
        subprocess,
        "CREATE_BREAKAWAY_FROM_JOB",
        _BREAKAWAY,
        raising=False,
    )
    attempts: list[dict[str, Any]] = []

    def fake_popen(_argv: list[str], **kwargs: Any) -> str:
        attempts.append(kwargs)
        raise FileNotFoundError(2, "not found")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    # When/Then
    with pytest.raises(FileNotFoundError):
        _ = proc.popen_detached(["missing"], close_fds=True)
    assert len(attempts) == 1


def test_breakaway_flag_is_owned_only_by_proc() -> None:
    # Given/When: every runtime module that spawns a survivor process.
    package = Path(proc.__file__).parent
    carriers = sorted(
        path.name
        for path in package.rglob("*.py")
        if "CREATE_BREAKAWAY_FROM_JOB" in path.read_text(encoding="utf-8")
    )

    # Then: the flag (and its WinError 5 fallback) lives in one place.
    assert carriers == ["proc.py"]
