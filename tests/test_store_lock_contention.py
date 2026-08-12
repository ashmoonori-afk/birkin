"""The native file lock remains exclusive under heavy contention."""

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
        """Contention retries must not turn the lock into a no-op."""
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
