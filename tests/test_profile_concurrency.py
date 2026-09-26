from __future__ import annotations

import functools
import multiprocessing as mp
import time
from pathlib import Path

import pytest

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
