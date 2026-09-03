"""Approval button taps are privileged.

An allowlisted chat is not enough: the tapping user must be named in
``allowed_sender_ids``, so an empty list refuses the tap instead of falling
back to the message-path compatibility rule (an empty list there means "no
extra sender restriction" — see ``test_telegram_channel_fixes``).
"""

from __future__ import annotations

from birkin.gateway.channels.telegram import TelegramChannel

_AID = "act-1"


class _ClaimGateway:
    """Duck-typed stand-in for the approval half of the gateway."""

    def __init__(self) -> None:
        self.claims: list[str] = []

    def claim_action(self, aid: str, *, actor_id: str, via: str) -> tuple[str, bool]:
        _ = (actor_id, via)
        self.claims.append(aid)
        # False: the action is not claimed for execution, so no worker starts.
        return ("claimed", False)


def _tap(
    senders: list[str],
    chat_id: int,
    chat_type: str,
    from_id: int,
) -> tuple[_ClaimGateway, list[tuple[str, dict[str, object]]]]:
    channel = TelegramChannel(
        "tok", allowed_chat_ids=["42"], allowed_sender_ids=senders, stream=False
    )
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(
        method: str, params: dict[str, object], *_a: object, **_k: object
    ) -> dict[str, object]:
        calls.append((method, params))
        return {"ok": True}

    channel._call = fake_call  # pyright: ignore[reportAttributeAccessIssue]
    gateway = _ClaimGateway()
    channel._handle_callback(
        gateway,  # pyright: ignore[reportArgumentType]
        {
            "id": "cb",
            "data": f"apv:{_AID}",
            "from": {"id": from_id},
            "message": {
                "chat": {"id": chat_id, "type": chat_type},
                "message_id": 7,
                "text": "x",
            },
        },
    )
    return gateway, calls


def test_group_tap_refused_when_sender_list_empty() -> None:
    gateway, calls = _tap([], 42, "supergroup", 999)
    assert gateway.claims == []
    assert [method for method, _ in calls] == ["answerCallbackQuery"]
    assert "allowed_sender_ids" in str(calls[0][1].get("text", ""))


def test_group_tap_applied_for_an_allowlisted_sender() -> None:
    gateway, _calls = _tap(["999"], 42, "supergroup", 999)
    assert gateway.claims == [_AID]


def test_private_tap_applied_without_a_sender_list() -> None:
    gateway, _calls = _tap([], 42, "private", 42)
    assert gateway.claims == [_AID]
