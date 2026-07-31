"""End-to-end: a due commitment reaches Telegram and a button tap closes it.

Drives the real send path (``scheduler.run_checkins``) and the real callback
handler against a Bot API-compatible stub, so the wiring between the domain, the
scheduler, and the channel is exercised without a network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from birkin import companion, config, scheduler
from birkin.gateway.channels.telegram import TelegramChannel

KST = timezone(timedelta(hours=9))
CHAT = "12345"
CTX = f"telegram:{CHAT}"
BASE = datetime(2026, 8, 1, 9, 0, tzinfo=KST)


class BotStub:
    """Records sends/edits/acks and hands back message ids."""

    def __init__(self):
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        self.acks: list[str] = []
        self._next_id = 1000

    def send(self, chat_id: str, text: str, markup: str) -> str:
        self._next_id += 1
        self.sent.append({"chat_id": chat_id, "text": text,
                          "markup": json.loads(markup),
                          "message_id": str(self._next_id)})
        return str(self._next_id)

    def call(self, method: str, params: dict, timeout: int = 60) -> dict:
        if method == "answerCallbackQuery":
            self.acks.append(str(params.get("text", "")))
        elif method == "editMessageText":
            self.edited.append(dict(params))
        return {"ok": True, "result": {"message_id": params.get("message_id", 1)}}


@pytest.fixture
def bot(monkeypatch):
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "channels": {"telegram": {"enabled": True, "token": "test-token",
                                     "allowed_chat_ids": [CHAT]}}}
    config.save_config(cfg)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    return BotStub()


def _ready(**policy):
    companion.bind_context(CTX, owner_id=CHAT)
    settings = {"enabled": True, "timezone": "Asia/Seoul",
                "utc_offset_minutes": 540, "daily_cap": 0,
                "cooldown_minutes": 0, "expiry_minutes": 0,
                "quiet_hours": {"start": "22:00", "end": "08:00"}}
    settings.update(policy)
    companion.set_policy(**settings)
    rec = companion.add_candidate(context_id=CTX, outcome="제안서 보내기",
                                  source_ref=f"{CTX}:99",
                                  next_action="개요 작성")
    return companion.activate(rec["id"], check_in_at=BASE.isoformat(),
                              tz_name="Asia/Seoul", utc_offset_minutes=540)


def _channel(bot, monkeypatch):
    channel = TelegramChannel("test-token", allowed_chat_ids=[CHAT])
    monkeypatch.setattr(channel, "_call", bot.call)
    return channel


def _tap(channel, commitment_id, verb, message_id="1001", chat=CHAT):
    cq = {"id": "cb1", "data": f"companion:{verb}:{commitment_id}",
          "from": {"id": chat},
          "message": {"chat": {"id": chat}, "message_id": message_id,
                      "text": "어제 확인해 달라고 하신 일이에요: 제안서 보내기"}}
    channel._handle_callback(None, cq)


def test_happy_path_send_then_done(bot, monkeypatch):
    rec = _ready()
    assert scheduler.run_checkins(now=BASE + timedelta(minutes=1),
                                  send=bot.send) == 1
    message = bot.sent[0]
    assert message["chat_id"] == CHAT
    assert rec["outcome"] in message["text"]
    assert "이 메시지는 당신이 직접 확인한 약속 때문에 보냈어요" in message["text"]
    buttons = [b["callback_data"] for row in message["markup"]["inline_keyboard"]
               for b in row]
    assert buttons == [f"companion:{verb}:{rec['id']}"
                       for verb in ("done", "blocked", "snooze", "stop", "wrong")]
    assert companion.get_commitment(rec["id"])["checkin"]["message_id"] == \
        message["message_id"]

    _tap(_channel(bot, monkeypatch), rec["id"], "done", message["message_id"])
    assert companion.get_commitment(rec["id"])["status"] == "done"
    assert bot.acks and "완료" in bot.acks[0]
    assert bot.edited and "완료로 기록했어요" in bot.edited[0]["text"]


def test_blocked_path_keeps_the_next_action(bot, monkeypatch):
    rec = _ready()
    scheduler.run_checkins(now=BASE + timedelta(minutes=1), send=bot.send)
    _tap(_channel(bot, monkeypatch), rec["id"], "blocked")
    after = companion.get_commitment(rec["id"])
    assert after["status"] == "blocked"
    assert after["next_action"] == "개요 작성"


def test_snooze_moves_the_next_check_in(bot, monkeypatch):
    rec = _ready()
    scheduler.run_checkins(now=BASE + timedelta(minutes=1), send=bot.send)
    _tap(_channel(bot, monkeypatch), rec["id"], "snooze")
    after = companion.get_commitment(rec["id"])
    assert after["status"] == "snoozed"
    # The tap runs on the real clock, as a live callback would, so the new time
    # is 60 minutes after the ANSWER, not after the simulated send time.
    answered = companion.parse_iso(after["checkin"]["answered_at"])
    assert companion.parse_iso(after["check_in_at"]) == \
        answered + timedelta(minutes=60)


@pytest.mark.parametrize("verb", ["stop", "wrong"])
def test_stop_and_wrong_close_the_commitment(bot, monkeypatch, verb):
    rec = _ready()
    scheduler.run_checkins(now=BASE + timedelta(minutes=1), send=bot.send)
    _tap(_channel(bot, monkeypatch), rec["id"], verb)
    assert companion.get_commitment(rec["id"])["status"] == "stopped"


def test_repeated_tap_is_idempotent(bot, monkeypatch):
    rec = _ready()
    scheduler.run_checkins(now=BASE + timedelta(minutes=1), send=bot.send)
    channel = _channel(bot, monkeypatch)
    _tap(channel, rec["id"], "done")
    _tap(channel, rec["id"], "done")
    answered = [e for e in companion.read_events(commitment_id=rec["id"])
                if e["type"] == "checkin_answered"]
    assert len(answered) == 1
    assert companion.get_commitment(rec["id"])["status"] == "done"


def test_bad_callback_data_changes_nothing(bot, monkeypatch):
    _ready()
    channel = _channel(bot, monkeypatch)
    for data in ("companion:", "companion:done:", "companion:done:nosuchid",
                 "companion:frobnicate:abc"):
        cq = {"id": "cb", "data": data, "from": {"id": CHAT},
              "message": {"chat": {"id": CHAT}, "message_id": "1", "text": "x"}}
        channel._handle_callback(None, cq)
    assert all(c["status"] == "active" for c in companion.list_commitments())


def test_a_tap_from_another_chat_cannot_close_the_commitment(bot, monkeypatch):
    rec = _ready()
    scheduler.run_checkins(now=BASE + timedelta(minutes=1), send=bot.send)
    channel = TelegramChannel("test-token", allowed_chat_ids=[CHAT, "999"])
    monkeypatch.setattr(channel, "_call", bot.call)
    _tap(channel, rec["id"], "done", chat="999")
    assert companion.get_commitment(rec["id"])["status"] == "active"
    assert "unauthorized" in bot.acks[-1]


def test_send_is_refused_when_the_chat_is_not_allowlisted(bot, monkeypatch):
    cfg = config.load_config()
    cfg["channels"]["telegram"]["allowed_chat_ids"] = ["999"]
    config.save_config(cfg)
    rec = _ready()
    # The real sender is used deliberately: the send-time allowlist re-check
    # lives there, so a stub would prove nothing.
    assert scheduler._send_checkin(CHAT, "body", "{}") is None
    assert scheduler.run_checkins(now=BASE + timedelta(minutes=1)) == 0
    failures = [e for e in companion.read_events(commitment_id=rec["id"])
                if e["type"] == "checkin_send_failed"]
    assert failures


def test_no_duplicate_send_across_two_scheduler_passes(bot, monkeypatch):
    _ready()
    first = scheduler.run_checkins(now=BASE + timedelta(minutes=1), send=bot.send)
    second = scheduler.run_checkins(now=BASE + timedelta(minutes=2), send=bot.send)
    assert (first, second) == (1, 0)
    assert len(bot.sent) == 1


def test_quiet_hours_suppress_the_send_entirely(bot, monkeypatch):
    companion.bind_context(CTX, owner_id=CHAT)
    companion.set_policy(enabled=True, timezone="Asia/Seoul",
                         utc_offset_minutes=540, daily_cap=0,
                         cooldown_minutes=0, expiry_minutes=0,
                         quiet_hours={"start": "22:00", "end": "08:00"})
    night = datetime(2026, 8, 1, 23, 0, tzinfo=KST)
    rec = companion.add_candidate(context_id=CTX, outcome="제안서 보내기",
                                  source_ref=f"{CTX}:99")
    companion.activate(rec["id"], check_in_at=night.isoformat(),
                       tz_name="Asia/Seoul", utc_offset_minutes=540)
    assert scheduler.run_checkins(now=night + timedelta(minutes=1),
                                  send=bot.send) == 0
    assert bot.sent == []


def test_gateway_chat_commands_inspect_and_pause(bot, monkeypatch):
    from birkin.gateway.core import Gateway
    rec = _ready()
    gateway = Gateway(config.load_config())
    out = gateway.companion_command("commitment", "", "telegram", CHAT)
    assert rec["outcome"] in out and "개요 작성" in out
    assert "켜짐" in gateway.companion_command("checkin", "", "telegram", CHAT)
    gateway.companion_command("checkin", "pause", "telegram", CHAT)
    assert companion.get_policy()["enabled"] is False
    gateway.companion_command("checkin", "on", "telegram", CHAT)
    assert companion.get_policy()["enabled"] is True
    assert "off" in gateway.companion_command("companion", "", "telegram", CHAT)
    gateway.companion_command("companion", "off", "telegram", CHAT)
    assert companion.get_policy()["enabled"] is False
