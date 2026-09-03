"""Regression tests for three Telegram channel fixes.

1. An empty ``allowed_sender_ids`` means "no extra sender restriction" only
   outside group chats: an allowlisted group stays fail-closed until its
   members are listed, otherwise any member could drive a privileged turn.
2. The getUpdates offset acknowledgement before a hard restart: the worker
   waits for the poll loop's next getUpdates instead of issuing one itself
   (that would 409 against our own long poll). Re-exec'ing before the ack has
   Telegram re-deliver the triggering update and the restart loops.
3. ``TELEGRAM_EXECUTION_POLICY`` lives in turn_support only, and the
   ChannelGateway protocol declares the signatures its callers actually use.
"""

from __future__ import annotations

import inspect
import threading
from pathlib import Path

import pytest

from birkin.gateway import core as gw_core
from birkin.gateway import turn_model, turn_support
from birkin.gateway.channels import build_channels
from birkin.gateway.channels.registry_types import Config
from birkin.gateway.channels.base import ChannelGateway
from birkin.gateway.channels.telegram import TelegramChannel


# ---------------- 1. sender authorization ----------------


def _channel(senders: list[str] | None = None) -> TelegramChannel:
    return TelegramChannel(
        "tok", allowed_chat_ids=["-1001"], allowed_sender_ids=senders, stream=False
    )


def test_group_member_refused_when_sender_list_empty() -> None:
    channel = _channel()
    assert not channel._sender_authorized("-1001", "777", "supergroup")
    assert not channel._sender_authorized("-1001", "777", "group")


def test_group_member_refused_when_absent_from_sender_list() -> None:
    channel = _channel(["555"])
    assert not channel._sender_authorized("-1001", "777", "supergroup")
    assert channel._sender_authorized("-1001", "555", "supergroup")


def test_private_chat_authorization_unchanged() -> None:
    private = TelegramChannel("tok", allowed_chat_ids=["42"], stream=False)
    assert private._sender_authorized("42", "42", "private")
    assert not private._sender_authorized("42", "", "private")
    assert not private._sender_authorized("99", "99", "private")


def test_build_channels_warns_about_open_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    cfg: Config = {
        "channels": {
            "http": {"enabled": False},
            "telegram": {"enabled": True, "allowed_chat_ids": ["-1001"]},
        }
    }
    _ = build_channels(cfg)
    assert "allowed_sender_ids" in capsys.readouterr().out


# ---------------- 2. offset ack before hard restart ----------------


class _RestartingGateway:
    pending_hard_restart = True

    def __init__(self, order: list[str], restarted: threading.Event) -> None:
        self._order = order
        self.restarted = restarted

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
        return "restarting"

    def do_hard_restart(self) -> None:
        self._order.append("restart")
        self.restarted.set()

    def interrupt(self, channel: str, chat_id: str) -> bool:
        return False

    def take_restart_greeting(self, channel: str) -> str | None:
        return None

    def command_menu(self) -> list[dict[str, str]]:
        return []


class _AckEvent(threading.Event):
    """The offset-ack event, recording who acked and who waited."""

    def __init__(self, order: list[str], waiting: threading.Event) -> None:
        super().__init__()
        self._order = order
        self._waiting = waiting

    def set(self) -> None:
        self._order.append("ack")
        super().set()

    def wait(self, timeout: float | None = None) -> bool:
        self._order.append("wait")
        self._waiting.set()
        return super().wait(timeout)


def test_hard_restart_waits_for_the_poll_loops_offset_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker must not re-exec until the poll loop has issued the
    getUpdates carrying the advanced offset — and must never poll itself."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    order: list[str] = []
    worker_waiting = threading.Event()
    restarted = threading.Event()
    gateway = _RestartingGateway(order, restarted)
    channel = TelegramChannel("tok", allowed_chat_ids=["42"], stream=False)
    channel._poll_acked = _AckEvent(order, worker_waiting)
    polls: list[tuple[int, object]] = []
    main_thread = threading.get_ident()

    def fake_call(method: str, params: dict[str, object], *a: object, **k: object):
        if method != "getUpdates":
            return {"ok": True}
        polls.append((threading.get_ident(), params.get("offset")))
        if len(polls) == 1:
            return {
                "ok": True,
                "result": [
                    {
                        "update_id": 1,
                        "message": {
                            "chat": {"id": "42", "type": "private"},
                            "from": {"id": "42"},
                            "text": "/hard-restart",
                        },
                    }
                ],
            }
        assert restarted.wait(5), "the acked worker never restarted"
        raise SystemExit

    start_worker = channel._start_public_worker

    def gated_start(*args: object, **kwargs: object) -> object:
        worker = start_worker(*args, **kwargs)  # pyright: ignore[reportCallIssue]
        # Hold the poll loop between dispatching the batch and its next
        # getUpdates, so a worker that skipped the wait would restart first.
        assert worker_waiting.wait(5), "the worker restarted without the ack"
        return worker

    monkeypatch.setattr(channel, "_call", fake_call)
    monkeypatch.setattr(channel, "_start_public_worker", gated_start)
    monkeypatch.setattr(channel, "_keep_typing", lambda *_a, **_k: None)
    monkeypatch.setattr(channel, "_deliver_reply", lambda *_a, **_k: True)

    with pytest.raises(SystemExit):
        channel.start(gateway)

    assert order == ["ack", "wait", "ack", "restart"]
    # Both polls on the poll loop's own thread: a second getUpdates from the
    # worker would make Telegram 409 against ourselves.
    assert [ident for ident, _ in polls] == [main_thread, main_thread]
    assert polls[1][1] == 2, "the ack must carry the advanced offset"


# ---------------- 3. one policy string, honest protocol ----------------


def test_execution_policy_has_one_source() -> None:
    assert (
        turn_model.TELEGRAM_EXECUTION_POLICY is turn_support.TELEGRAM_EXECUTION_POLICY
    )
    source = Path(turn_model.__file__ or "").read_text(encoding="utf-8")
    assert "TELEGRAM_EXECUTION_POLICY = (" not in source


@pytest.mark.parametrize("name", ["resolve_action", "claim_action"])
def test_channel_gateway_protocol_matches_gateway(name: str) -> None:
    declared = inspect.signature(getattr(ChannelGateway, name))
    actual = inspect.signature(getattr(gw_core.Gateway, name))
    assert list(declared.parameters) == list(actual.parameters)
    for param in ("actor_id", "via"):
        assert declared.parameters[param].kind is inspect.Parameter.KEYWORD_ONLY
