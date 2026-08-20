from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

from birkin.rolefiles import ProfileEdit, ProfileStore


def _append_many(home: str, label: str, barrier: object, count: int) -> None:
    store = ProfileStore(Path(home), {})
    barrier.wait()
    for index in range(count):
        store.apply(ProfileEdit("preferences", "add", content=f"{label}-{index}"))


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
    for process in processes:
        process.join(20)
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join(5)
        assert process.exitcode == 0

    entries = ProfileStore(tmp_path, {}).snapshot().documents["preferences"].entries
    expected = {f"worker-{i}-{j}" for i in range(workers) for j in range(count)}
    assert set(entries) == expected
    assert len(entries) == workers * count
