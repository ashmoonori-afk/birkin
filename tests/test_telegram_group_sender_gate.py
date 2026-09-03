"""An allowlisted group with no ``allowed_sender_ids`` must stay fail-closed.

Allowlisting only the group id is the natural single config step, so if that
alone authorized turns, every member of the group would get a fully
capability-enabled agent turn in the owner's workspace (poll loop ->
``_sender_authorized`` is the only channel-level gate before ``_run_turn``).
"""

from __future__ import annotations

from birkin.gateway.channels.telegram import TelegramChannel


def _group_channel() -> TelegramChannel:
    return TelegramChannel(
        "tok", allowed_chat_ids=["-1001234567890"], allowed_sender_ids=[], stream=False
    )


def test_group_turn_refused_when_sender_list_empty() -> None:
    channel = _group_channel()
    for chat_type in ("group", "supergroup"):
        assert not channel._sender_authorized(
            "-1001234567890", "55555", chat_type
        ), chat_type
        assert not channel._sender_authorized(
            "-1001234567890", "55555", chat_type, privileged=True
        ), chat_type


def test_group_turn_allowed_for_listed_sender() -> None:
    channel = TelegramChannel(
        "tok",
        allowed_chat_ids=["-1001234567890"],
        allowed_sender_ids=["55555"],
        stream=False,
    )
    assert channel._sender_authorized("-1001234567890", "55555", "supergroup")
    assert not channel._sender_authorized("-1001234567890", "777", "supergroup")


def test_private_chat_still_allowed_without_sender_list() -> None:
    private = TelegramChannel("tok", allowed_chat_ids=["42"], stream=False)
    assert private._sender_authorized("42", "42", "private")
