from __future__ import annotations

import errno
import functools
import multiprocessing as mp
import os
import time
from pathlib import Path
from typing import Any

import pytest

from birkin import profile_lock as profile_lock_module
from birkin import rolefiles
from birkin.profile_lock import ProfileLockTimeout, profile_lock
from birkin.rolefiles import ProfileEdit, ProfileStore

# The lost-update test asserts serialization, not lock latency. The Windows lock
# polls without fairness, so on a loaded runner one worker can wait past the
# production 5 s default while the others keep winning.
_WORKER_LOCK_TIMEOUT = 60.0
_WORKER_JOIN_DEADLINE = 120.0


def _append_many(home: str, label: str, barrier: object, count: int) -> None:
    rolefiles.profile_lock = functools.partial(
        profile_lock, timeout=_WORKER_LOCK_TIMEOUT
    )
    store = ProfileStore(Path(home), {})
    barrier.wait()
    for index in range(count):
        store.apply(ProfileEdit("preferences", "add", content=f"{label}-{index}"))


@pytest.fixture(params=["open", "fdopen"])
def operation(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _hold_lock(home: str, ready: object, release: object) -> None:
    with profile_lock(Path(home)):
        ready.set()
        release.wait()


def test_profile_lock_timeout_is_typed_and_names_path(tmp_path: Path) -> None:
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    release = ctx.Event()
    process = ctx.Process(target=_hold_lock, args=(str(tmp_path), ready, release))
    process.start()
    try:
        assert ready.wait(10)
        with pytest.raises(ProfileLockTimeout) as captured:
            with profile_lock(tmp_path, timeout=0):
                pass
        assert str((tmp_path / "profile" / ".profile.lock").resolve()) in str(captured.value)
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0


def test_profile_lock_prevents_lost_updates_between_processes(tmp_path: Path) -> None:
    ctx = mp.get_context("spawn")
    workers = 4
    count = 12
    barrier = ctx.Barrier(workers)
    processes = [
        ctx.Process(target=_append_many, args=(str(tmp_path), f"worker-{i}", barrier, count))
        for i in range(workers)
    ]

    for process in processes:
        process.start()
    deadline = time.monotonic() + _WORKER_JOIN_DEADLINE
    for process in processes:
        process.join(max(0.0, deadline - time.monotonic()))
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join(5)
        assert process.exitcode == 0

    entries = ProfileStore(tmp_path, {}).snapshot().documents["preferences"].entries
    expected = {f"worker-{i}-{j}" for i in range(workers) for j in range(count)}
    assert set(entries) == expected
    assert len(entries) == workers * count


def _entry_count(path: Path) -> int:
    entry = profile_lock_module._HELD.get(path)
    return 0 if entry is None else entry[1]


def test_profile_lock_recovers_after_open_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    root = tmp_path / "profile"
    root.mkdir(parents=True, exist_ok=True)
    path = (root / ".profile.lock").resolve()
    real_open = os.open
    real_fdopen = os.fdopen
    leaked: list[int] = []

    if operation == "open":

        def raising_open(*args: object, **kwargs: object) -> int:
            raise PermissionError("injected open failure")

        monkeypatch.setattr(os, "open", raising_open)
    else:

        def capturing_open(*args: Any, **kwargs: Any) -> int:
            fd = real_open(*args, **kwargs)
            leaked.append(fd)
            return fd

        def raising_fdopen(*args: Any, **kwargs: Any) -> Any:
            raise PermissionError("injected fdopen failure")

        monkeypatch.setattr(os, "open", capturing_open)
        monkeypatch.setattr(os, "fdopen", raising_fdopen)

    entered = False
    with pytest.raises(PermissionError, match="injected"):
        with profile_lock(tmp_path, timeout=0):
            entered = True
    assert entered is False
    assert _entry_count(path) == 0
    if operation == "fdopen":
        assert leaked
        with pytest.raises(OSError) as closed:
            _ = os.fstat(leaked[0])
        assert closed.value.errno == errno.EBADF

    monkeypatch.setattr(os, "open", real_open)
    monkeypatch.setattr(os, "fdopen", real_fdopen)

    acquisitions = 0
    real_lock_file = profile_lock_module._lock_file

    def counting_lock_file(handle: Any, path: Path, timeout: float) -> None:
        nonlocal acquisitions
        acquisitions += 1
        real_lock_file(handle, path, timeout)

    monkeypatch.setattr(profile_lock_module, "_lock_file", counting_lock_file)
    with profile_lock(tmp_path, timeout=0):
        assert _entry_count(path) == 1
        assert acquisitions == 1
    assert _entry_count(path) == 0
    assert acquisitions == 1
