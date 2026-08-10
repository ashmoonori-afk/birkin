"""The lock must treat Windows's PermissionError as contention, not failure.

store.file_lock spins on os.open(O_CREAT | O_EXCL). On POSIX, losing the race
raises FileExistsError, which the spin already retries. On Windows the SAME
loss can surface as PermissionError instead: the winner may hold the file open
or be mid-unlink, and Windows refuses the open with EACCES rather than EEXIST.

The old loop let PermissionError escape, so a worker that merely lost a race
crashed -- the intermittent failure test_concurrent_bundled_skill_improvements
_keep_both_notes has shown under load since the 2026-07-29 audit recorded it.

This test makes the race a certainty instead of a coincidence: many threads
hammer one lock, and the loser path is exercised thousands of times.
"""

from __future__ import annotations

import threading

from birkin import store


def _hammer(lock_path, workers: int, rounds: int) -> tuple[int, list[str]]:
    """Many threads contending for one lock; returns (completed, errors)."""
    counter = {"value": 0}
    errors: list[str] = []
    barrier = threading.Barrier(workers)

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            for _ in range(rounds):
                with store.file_lock(lock_path):
                    counter["value"] += 1
        except Exception as exc:                      # noqa: BLE001 - recording
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return counter["value"], errors


class TestLockUnderContention:
    def test_every_loser_retries_instead_of_crashing(self, tmp_path) -> None:
        completed, errors = _hammer(tmp_path / "notes.lock", workers=8, rounds=50)
        assert errors == [], f"losing the race must retry, not raise: {errors[:3]}"
        assert completed == 8 * 50

    def test_the_lock_still_excludes(self, tmp_path) -> None:
        """Retrying on PermissionError must not turn the lock into a no-op."""
        active = {"count": 0, "max": 0}
        errors: list[str] = []

        def worker() -> None:
            try:
                for _ in range(30):
                    with store.file_lock(tmp_path / "excl.lock"):
                        active["count"] += 1
                        active["max"] = max(active["max"], active["count"])
                        active["count"] -= 1
            except Exception as exc:                  # noqa: BLE001 - recording
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert errors == []
        assert active["max"] == 1, "two holders inside the critical section"


def test_a_permissionerror_loss_is_retried(tmp_path, monkeypatch) -> None:
    """The Windows race, made deterministic: the first N attempts lose with
    EACCES, exactly as Windows reports a winner holding the file."""
    import os as _os

    real_open = _os.open
    losses = {"left": 3}

    def flaky_open(path, flags, *args, **kwargs):
        if "flaky.lock" in str(path) and (flags & _os.O_EXCL) and losses["left"] > 0:
            losses["left"] -= 1
            raise PermissionError(13, "Access is denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(_os, "open", flaky_open)
    with store.file_lock(tmp_path / "flaky.lock"):
        pass                                          # acquiring at all is the pass
    assert losses["left"] == 0, "the retry loop never consumed the losses"
