from __future__ import annotations

import threading

from birkin.gateway.channels.telegram import TelegramChannel


def test_telegram_public_workers_are_bounded_and_evicted() -> None:
    channel = TelegramChannel("synthetic-test-token")
    release = threading.Event()
    condition = threading.Condition()
    started = 0

    def blocked() -> None:
        nonlocal started
        with condition:
            started += 1
            condition.notify_all()
        release.wait()

    workers = [
        channel._start_public_worker(
            channel._workers,
            f"chat-{index}",
            blocked,
            (),
        )
        for index in range(4)
    ]
    with condition:
        assert condition.wait_for(lambda: started == 4, timeout=2.0)

    fifth = channel._start_public_worker(
        channel._workers,
        "chat-4",
        blocked,
        (),
    )

    assert all(worker is not None for worker in workers)
    assert fifth is None
    release.set()
    for worker in workers:
        assert worker is not None
        worker.join(timeout=2.0)
        assert not worker.is_alive()
    assert channel._workers == {}


def test_telegram_worker_limit_is_configurable() -> None:
    channel = TelegramChannel(
        "synthetic-test-token",
        max_public_workers=1,
    )
    release = threading.Event()
    started = threading.Event()

    def blocked() -> None:
        started.set()
        release.wait()

    first = channel._start_public_worker(
        channel._workers,
        "chat-1",
        blocked,
        (),
    )
    assert started.wait(timeout=2.0)
    second = channel._start_public_worker(
        channel._workers,
        "chat-2",
        blocked,
        (),
    )
    try:
        assert first is not None
        assert second is None
    finally:
        release.set()
        assert first is not None
        first.join(timeout=2.0)
