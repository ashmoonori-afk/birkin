"""User-visible reply for a Telegram turn interrupted by the next message."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from birkin.gateway.channels.telegram import TelegramChannel
from birkin.gateway.core import Gateway


class _EmptyInterruptedSession:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.interrupted = threading.Event()

    def ask(
        self,
        text: str,
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        self.started.set()
        assert self.interrupted.wait(timeout=2)
        return ""

    def interrupt(self) -> bool:
        self.interrupted.set()
        return True

    def is_alive(self) -> bool:
        return True

    def close(self) -> None:
        pass


def _gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Gateway:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config

    config.save_config(
        {
            **config.DEFAULT_CONFIG,
            "provider": "codex-cli",
            "model": "gpt-5.6-sol",
            "gateway_prewarm": False,
            "channels": {
                **config.DEFAULT_CONFIG["channels"],
                "telegram": {
                    "enabled": True,
                    "token": "test-token",
                    "allowed_chat_ids": ["42"],
                    "stream": False,
                },
            },
        }
    )
    return Gateway(config.load_config())


def test_telegram_labels_empty_interrupted_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway(tmp_path, monkeypatch)
    session = _EmptyInterruptedSession()
    gateway._claude_sessions.put(("telegram", "42"), session)
    channel = TelegramChannel("tok", allowed_chat_ids=["42"], stream=False)
    sent: list[str] = []
    monkeypatch.setattr(
        channel,
        "_keep_typing",
        lambda _chat_id, stop, _progress=None: stop.wait(),
    )
    monkeypatch.setattr(
        channel, "_send_reply", lambda _chat_id, reply: sent.append(reply)
    )
    worker = threading.Thread(
        target=channel._run_turn,
        args=(gateway, "42", "first", 0),
    )

    worker.start()
    assert session.started.wait(timeout=2)
    assert gateway.interrupt("telegram", "42") is True
    worker.join(timeout=3)

    assert not worker.is_alive()
    assert sent == ["(interrupted :o)"]
