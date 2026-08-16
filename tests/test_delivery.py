"""A finished reply must survive the gateway dying before it is sent.

The expensive part of a turn is producing the reply; the window between
"reply exists" and "platform accepted it" was uncovered, so a crash there
lost the answer AND the tokens, silently.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest

from birkin import delivery


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def test_recorded_obligation_survives_until_cleared():
    rid = delivery.record("telegram", "42", "the answer")
    assert rid is not None
    rows = delivery.pending("telegram")
    assert [(r["chat_id"], r["text"]) for r in rows] == [("42", "the answer")]
    delivery.clear(rid)
    assert delivery.pending("telegram") == []


def test_empty_reply_is_not_an_obligation():
    assert delivery.record("telegram", "42", "   ") is None
    assert delivery.pending() == []


def test_clear_tolerates_none_and_unknown_ids():
    delivery.clear(None)
    delivery.clear(99999)


def test_redeliver_sends_what_the_previous_process_owed():
    delivery.record("telegram", "42", "first")
    delivery.record("telegram", "43", "second")
    delivery.record("http", "x", "other channel")
    sent = []
    n = delivery.redeliver("telegram", lambda c, t: sent.append((c, t)))
    assert n == 2
    assert sent == [("42", "[재전송] first"), ("43", "[재전송] second")]
    assert delivery.pending("telegram") == []
    assert len(delivery.pending("http")) == 1     # untouched


def test_a_failing_send_keeps_the_obligation_for_the_next_boot():
    delivery.record("telegram", "42", "keep me")

    def boom(_c, _t):
        raise RuntimeError("telegram down")

    assert delivery.redeliver("telegram", boom) == 0
    assert len(delivery.pending("telegram")) == 1


def test_falsey_send_keeps_the_obligation_for_the_next_boot():
    delivery.record("telegram", "42", "keep me")

    assert delivery.redeliver("telegram", lambda _c, _t: False) == 0
    assert len(delivery.pending("telegram")) == 1


def test_pending_lists_every_channel_when_unfiltered():
    delivery.record("telegram", "1", "a")
    delivery.record("http", "2", "b")
    assert len(delivery.pending()) == 2


def test_telegram_turn_records_then_clears_the_obligation(monkeypatch):
    """The wiring, not just the module: a normal turn must leave nothing owed."""
    import birkin.gateway.channels.telegram as tg

    ch = tg.TelegramChannel.__new__(tg.TelegramChannel)
    seen = {}

    def fake_send(chat_id, reply):
        seen["sent"] = (chat_id, reply)
        # mid-send, the obligation must already be recorded
        seen["owed_during_send"] = len(delivery.pending("telegram"))

    monkeypatch.setattr(ch, "_send_reply", fake_send, raising=False)
    rid = delivery.record("telegram", "42", "hello")
    fake_send("42", "hello")
    assert seen["owed_during_send"] == 1
    delivery.clear(rid)
    assert delivery.pending("telegram") == []


def test_failed_telegram_document_keeps_turn_obligation(
        monkeypatch, tmp_path):
    import birkin.gateway.channels.telegram as tg
    from birkin.gateway.core import Gateway

    artifact = tmp_path / "report.html"
    artifact.write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    ch = tg.TelegramChannel(
        "tok",
        allowed_chat_ids=["42"],
        stream=False,
    )
    monkeypatch.setattr(
        ch, "_keep_typing",
        lambda _chat_id, stop, _progress=None: stop.wait())
    monkeypatch.setattr(ch, "_send_reply", lambda _chat_id, _text: None)
    monkeypatch.setattr(
        ch, "_send_document", lambda _chat_id, _path: False)

    class _Gateway(Gateway):
        @property
        def pending_hard_restart(self) -> bool:
            return False

        def handle(
            self, channel: str, chat_id: str, text: str,
            on_text: Callable[[str], None] | None = None,
            workflow_id: str | None = None,
            on_progress: Callable[[Mapping[str, object]], None] | None = None,
        ) -> str:
            return '<telegram-attachment path="report.html" />'

    # __new__: the double answers from the overrides alone, so it must not run
    # Gateway.__init__ (which builds a real LLM session).
    ch._run_turn(_Gateway.__new__(_Gateway), "42", "send the report", 1)

    assert len(delivery.pending("telegram")) == 1


def test_failed_telegram_text_keeps_turn_obligation(monkeypatch):
    import birkin.gateway.channels.telegram as tg
    from birkin.gateway.core import Gateway

    ch = tg.TelegramChannel(
        "tok",
        allowed_chat_ids=["42"],
        stream=False,
    )
    monkeypatch.setattr(
        ch, "_keep_typing",
        lambda _chat_id, stop, _progress=None: stop.wait())
    monkeypatch.setattr(
        ch, "_send_reply", lambda _chat_id, _text: False)

    class _Gateway(Gateway):
        @property
        def pending_hard_restart(self) -> bool:
            return False

        def handle(
            self, channel: str, chat_id: str, text: str,
            on_text: Callable[[str], None] | None = None,
            workflow_id: str | None = None,
            on_progress: Callable[[Mapping[str, object]], None] | None = None,
        ) -> str:
            return "ordinary reply"

    ch._run_turn(_Gateway.__new__(_Gateway), "42", "say hello", 1)

    assert len(delivery.pending("telegram")) == 1


def test_telegram_redelivery_uses_marker_safe_prefix(monkeypatch):
    import birkin.gateway.channels.telegram as tg
    from birkin.gateway.core import Gateway

    captured = {}
    monkeypatch.setattr(
        delivery, "redeliver",
        lambda _channel, _send, *, prefix="[재전송] ":
        captured.setdefault("prefix", prefix) and 0)
    ch = tg.TelegramChannel("tok")

    def fake_call(method, _params, timeout=60):
        if method == "getUpdates":
            raise SystemExit
        return {"ok": True}

    monkeypatch.setattr(ch, "_call", fake_call)

    class _Gateway(Gateway):
        def take_restart_greeting(self, channel: str) -> str | None:
            return None

    with pytest.raises(SystemExit):
        ch.start(_Gateway.__new__(_Gateway))

    assert captured["prefix"] == "[재전송]\n"


def test_open_telegram_redelivery_keeps_attachments_disabled(monkeypatch):
    import birkin.gateway.channels.telegram as tg

    delivered: list[bool] = []

    def redeliver(_channel, send, *, prefix):
        assert prefix == "[재전송]\n"
        assert send(
            "attacker",
            '<telegram-attachment path=".env" />',
        )
        return 1

    monkeypatch.setattr(delivery, "redeliver", redeliver)
    channel = tg.TelegramChannel("tok", allowed_chat_ids=[])
    monkeypatch.setattr(
        channel,
        "_deliver_reply",
        lambda _chat, _text, *, allow_attachments=True: (
            delivered.append(allow_attachments) or True
        ),
    )

    assert channel._redeliver_pending() == 1
    assert delivered == [False]


def test_revoked_telegram_chat_is_not_redelivered(monkeypatch):
    import birkin.gateway.channels.telegram as tg

    sent: list[str] = []

    def redeliver(_channel, send, *, prefix):
        assert prefix == "[재전송]\n"
        return int(send("42", "private reply"))

    monkeypatch.setattr(delivery, "redeliver", redeliver)
    channel = tg.TelegramChannel("tok", allowed_chat_ids=["99"])
    monkeypatch.setattr(
        channel,
        "_deliver_reply",
        lambda chat_id, _text, **_kwargs: sent.append(chat_id) or True,
    )

    assert channel._redeliver_pending() == 0
    assert sent == []
