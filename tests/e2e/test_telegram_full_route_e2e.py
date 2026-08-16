"""Offline Telegram route: chat, approval, media, and duplicate recovery."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from birkin import companion, config, scheduler, store
from birkin.gateway.channels import telegram as telegram_module
from birkin.gateway.channels.telegram import TelegramChannel
from birkin.gateway.core import Gateway

KST = timezone(timedelta(hours=9))
CHAT = "42"
CTX = f"telegram:{CHAT}"


def _gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Gateway:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    cfg = {
        **config.DEFAULT_CONFIG,
        "provider": "anthropic",
        "model": "fake",
        "gateway_prewarm": False,
        "gateway_persistent": False,
        "checkpoints": False,
        "channels": {
            "telegram": {
                "enabled": True,
                "token": "fake-token",
                "allowed_chat_ids": [CHAT],
                "stream": False,
            }
        },
    }
    config.save_config(cfg)
    gateway = Gateway(config.load_config())
    monkeypatch.setattr(
        gateway.session,
        "ask",
        lambda text, **_kwargs: f"reply:{text}",
    )
    return gateway


def test_fake_bot_api_routes_chat_and_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway(tmp_path, monkeypatch)
    channel = TelegramChannel(
        "fake-token",
        allowed_chat_ids=[CHAT],
        stream=False,
    )
    sent: list[str] = []
    monkeypatch.setattr(
        channel,
        "_send_reply",
        lambda _chat_id, text: sent.append(text) or True,
    )
    monkeypatch.setattr(
        channel,
        "_call",
        lambda _method, _params, timeout=60: {
            "ok": True,
            "result": {"message_id": 1},
        },
    )
    completed = threading.Event()
    execute_claimed = telegram_module.execute_claimed_with_progress

    def execute_and_signal(*args: Any, **kwargs: Any) -> str:
        try:
            return execute_claimed(*args, **kwargs)
        finally:
            completed.set()

    monkeypatch.setattr(
        telegram_module,
        "execute_claimed_with_progress",
        execute_and_signal,
    )

    channel._run_turn(gateway, CHAT, "ordinary chat", 1)
    pending = store.add_pending(
        category="memory",
        title="safe approval",
        description="offline approval",
        payload={"kind": "noop"},
    )
    channel._handle_callback(
        gateway,
        {
            "id": "callback-1",
            "data": f"apv:{pending['id']}",
            "from": {"id": int(CHAT)},
            "message": {
                "chat": {"id": int(CHAT)},
                "message_id": 2,
                "text": "Approve?",
            },
        },
    )
    assert completed.wait(timeout=5)

    assert sent[0].startswith("reply:")
    assert sent[0].endswith("ordinary chat")
    assert store.get_pending(pending["id"])["status"] == "approved"


def test_fake_bot_api_routes_media_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    upload = tmp_path / "uploads" / "photo.jpg"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"fake-image")
    channel = TelegramChannel("fake-token", allowed_chat_ids=[CHAT])
    monkeypatch.setattr(channel, "_download_media", lambda _file_id: str(upload))

    text = channel._compose_media_text(
        {
            "photo": [{"file_id": "small", "file_size": 1}],
            "caption": "inspect this",
        }
    )

    assert text is not None
    assert "inspect this" in text
    assert str(upload) in text


def test_duplicate_recovery_sends_one_checkin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    config.save_config(
        {
            **config.DEFAULT_CONFIG,
            "provider": "anthropic",
            "model": "fake",
            "channels": {
                "telegram": {
                    "enabled": True,
                    "token": "fake-token",
                    "allowed_chat_ids": [CHAT],
                }
            },
        }
    )
    companion.bind_context(CTX, owner_id=CHAT)
    companion.set_policy(
        enabled=True,
        timezone="Asia/Seoul",
        utc_offset_minutes=540,
        daily_cap=0,
        cooldown_minutes=0,
        expiry_minutes=0,
        quiet_hours=None,
    )
    due = datetime(2026, 8, 1, 9, 0, tzinfo=KST)
    record = companion.add_candidate(
        context_id=CTX,
        outcome="send one update",
        source_ref=f"{CTX}:1",
    )
    companion.activate(
        record["id"],
        check_in_at=due.isoformat(),
        tz_name="Asia/Seoul",
        utc_offset_minutes=540,
    )
    sent: list[dict[str, Any]] = []

    def send(chat_id: str, text: str, markup: str) -> str:
        sent.append({"chat_id": chat_id, "text": text, "markup": markup})
        return "1"

    first = scheduler.run_checkins(
        now=due + timedelta(minutes=1),
        send=send,
    )
    second = scheduler.run_checkins(
        now=due + timedelta(minutes=2),
        send=send,
    )

    assert (first, second) == (1, 0)
    assert len(sent) == 1
