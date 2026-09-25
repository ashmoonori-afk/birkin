"""Read-only and bookkeeping commands must not interrupt a running turn.

A /pending, /help or /commitment sent while a turn (or an approved workflow)
is running used to mark the workflow interrupted, cancel the turn, and block
the single poll thread for up to 20s joining it. Those commands start no model
turn and reset no session state, so they are answered beside the running turn.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import cast

import pytest

from birkin.gateway.channels import telegram as telegram_module
from birkin.gateway.channels.base import ChannelGateway
from birkin.gateway.channels.telegram import TelegramChannel


class _StopPolling(BaseException):
    pass


class _Gateway:
    pending_hard_restart = False

    def __init__(self, on_interrupt: threading.Event | None = None) -> None:
        self.interrupts: list[str] = []
        self.handled: list[tuple[str, str | None]] = []
        self._on_interrupt = on_interrupt

    def command_menu(self) -> list[dict[str, str]]:
        return []

    def take_restart_greeting(self, _channel: str) -> None:
        return None

    def _command_trusted(self, _channel: str) -> bool:
        return True

    def interrupt(self, _channel: str, chat_id: str) -> bool:
        self.interrupts.append(chat_id)
        if self._on_interrupt is not None:
            self._on_interrupt.set()
        return True

    def handle(
        self,
        channel: str,
        chat_id: str,
        text: str,
        on_text: object = None,
        workflow_id: str | None = None,
        on_progress: object = None,
        sender_id: str | None = None,
    ) -> str:
        del channel, chat_id, on_text, workflow_id, on_progress
        self.handled.append((text, sender_id))
        return f"reply to {text}"

    def do_hard_restart(self) -> None:
        raise AssertionError("unexpected restart")


def _drive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway: _Gateway,
    text: str,
    release: threading.Event,
    *,
    max_public_workers: int = 4,
    busy_slots: int = 0,
) -> tuple[TelegramChannel, threading.Thread, list[str], float]:
    """Run one update for chat 42 while a turn and a workflow are in flight."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    channel = TelegramChannel("tok", allowed_chat_ids=["42"], stream=False,
                              max_public_workers=max_public_workers)
    for _ in range(busy_slots):
        assert channel._worker_slots.acquire(blocking=False)
    running = threading.Thread(target=release.wait, args=(30,), daemon=True)
    running.start()
    channel._workers["42"] = running
    channel._workflow_ids["42"] = "wf-demo"
    marked: list[str] = []
    batches = [
        [
            {
                "update_id": 1,
                "message": {
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 42},
                    "text": text,
                },
            }
        ]
    ]

    def call(method: str, _params: dict[str, object], timeout: int = 60) -> object:
        del timeout
        if method != "getUpdates":
            return {"ok": True}
        if batches:
            return {"ok": True, "result": batches.pop(0)}
        raise _StopPolling

    monkeypatch.setattr(channel, "_redeliver_pending", lambda: 0)
    monkeypatch.setattr(telegram_module, "restore_stranded_claims", lambda: 0)
    monkeypatch.setattr(telegram_module, "mark_interrupted", marked.append)
    monkeypatch.setattr(channel, "_call", call)
    started = time.monotonic()
    with pytest.raises(_StopPolling):
        channel.start(cast(ChannelGateway, gateway))
    return channel, running, marked, time.monotonic() - started


def test_pending_leaves_running_workflow_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    gateway = _Gateway()
    shown = threading.Event()
    shown_for: list[str] = []

    def send_pending(_gateway: object, chat_id: str) -> None:
        shown_for.append(chat_id)
        shown.set()

    monkeypatch.setattr(
        TelegramChannel, "_send_pending_buttons", lambda _self, g, c: send_pending(g, c)
    )
    try:
        channel, running, marked, elapsed = _drive(
            tmp_path, monkeypatch, gateway, "/pending", release
        )
        assert shown.wait(timeout=5)
        assert shown_for == ["42"]
        assert gateway.interrupts == []
        assert marked == []
        assert elapsed < 5
        assert running.is_alive()
        assert channel._workers["42"] is running
    finally:
        release.set()


@pytest.mark.parametrize(
    "text", ["/help", "/commitment", "/remind list", "/summon"]
)
def test_side_command_is_answered_without_interrupting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    release = threading.Event()
    gateway = _Gateway()
    delivered = threading.Event()
    replies: list[tuple[str, str]] = []

    def deliver(chat_id: str, reply: str, *_a: object, **_k: object) -> bool:
        replies.append((chat_id, reply))
        delivered.set()
        return True

    monkeypatch.setattr(
        TelegramChannel, "_deliver_reply", lambda _self, *a, **k: deliver(*a, **k)
    )
    try:
        channel, running, marked, elapsed = _drive(
            tmp_path, monkeypatch, gateway, text, release
        )
        assert delivered.wait(timeout=5)
        assert gateway.handled == [(text, "42")]
        assert replies == [("42", f"reply to {text}")]
        assert gateway.interrupts == []
        assert marked == []
        assert elapsed < 5
        assert channel._workers["42"] is running
    finally:
        release.set()


def test_plain_text_still_interrupts_running_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    gateway = _Gateway(on_interrupt=release)
    turns: list[str] = []

    def capture_turn(
        _gateway: object,
        _chat_id: str,
        text: str,
        _offset: int,
        sender_id: str | None = None,
        *,
        offset_ack: threading.Event | None = None,
    ) -> None:
        del sender_id, offset_ack
        turns.append(text)

    monkeypatch.setattr(
        TelegramChannel, "_run_turn", lambda _self, *a, **k: capture_turn(*a, **k)
    )
    channel, running, marked, _elapsed = _drive(
        tmp_path, monkeypatch, gateway, "do something else", release
    )
    running.join(timeout=5)
    worker = channel._workers.get("42")
    if worker is not None:
        worker.join(timeout=5)
    assert marked == ["wf-demo"]
    assert gateway.interrupts == ["42"]
    assert turns == ["do something else"]


def test_pending_still_answers_inline_when_every_worker_slot_is_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    gateway = _Gateway()
    shown_for: list[str] = []
    busy: list[str] = []

    monkeypatch.setattr(
        TelegramChannel, "_send_pending_buttons",
        lambda _self, _g, chat_id: shown_for.append(chat_id),
    )
    monkeypatch.setattr(
        TelegramChannel, "_send_plain",
        lambda _self, chat_id, _text: busy.append(chat_id),
    )
    try:
        _channel, running, marked, _elapsed = _drive(
            tmp_path, monkeypatch, gateway, "/pending", release,
            max_public_workers=1, busy_slots=1,
        )
        assert shown_for == ["42"] and busy == []
        assert gateway.interrupts == [] and marked == []
        assert running.is_alive()
    finally:
        release.set()
