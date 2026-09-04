from __future__ import annotations

import threading
from collections.abc import Callable
from typing import cast

import pytest

from birkin.gateway.channels import telegram as telegram_module
from birkin.gateway.channels.base import ChannelGateway
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


def test_poll_worker_binds_authorized_update_before_later_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel = TelegramChannel(
        "synthetic-test-token",
        allowed_chat_ids=["42"],
    )
    queued: list[Callable[[], None]] = []
    turns: list[tuple[object, str, str, int, str | None, str | None]] = []
    updates = {
        "result": [
            {
                "update_id": 10,
                "message": {
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 42},
                    "text": "authorized text",
                },
            },
            {
                "update_id": 11,
                "message": {
                    "chat": {"id": 99, "type": "private"},
                    "from": {"id": 99},
                    "text": "unauthorized text",
                },
            },
        ]
    }

    class Gateway:
        def command_menu(self) -> list[dict[str, str]]:
            return []

        def take_restart_greeting(self, _channel: str) -> None:
            return None

        def interrupt(self, _channel: str, _chat_id: str) -> bool:
            return False

    gateway = Gateway()

    def fake_call(
        method: str,
        _params: dict[str, object],
        timeout: int = 30,
    ) -> dict[str, object]:
        del timeout
        if method == "getUpdates":
            if updates:
                response = updates.copy()
                updates.clear()
                return response
            raise KeyboardInterrupt
        return {}

    def queue_worker(
        _registry: dict[str, threading.Thread],
        _key: str,
        target: Callable[[], None],
        _args: tuple[object, ...] = (),
    ) -> object:
        queued.append(target)
        return object()

    def capture_turn(
        received_gateway: object,
        chat_id: str,
        text: str,
        offset: int,
        workflow_id: str | None = None,
        sender_id: str | None = None,
        *,
        offset_ack: threading.Event | None = None,
    ) -> None:
        del offset_ack
        turns.append(
            (received_gateway, chat_id, text, offset, workflow_id, sender_id)
        )

    monkeypatch.setattr(channel, "_redeliver_pending", lambda: 0)
    monkeypatch.setattr(telegram_module, "restore_stranded_claims", lambda: 0)
    monkeypatch.setattr(channel, "_call", fake_call)
    monkeypatch.setattr(channel, "_start_public_worker", queue_worker)
    monkeypatch.setattr(channel, "_run_turn", capture_turn)

    with pytest.raises(KeyboardInterrupt):
        channel.start(cast(ChannelGateway, gateway))

    assert len(queued) == 1
    queued[0]()
    assert turns == [(gateway, "42", "authorized text", 11, None, "42")]
