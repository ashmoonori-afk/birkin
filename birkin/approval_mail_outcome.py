"""Honest terminal outcome for approved Microsoft 365 mail sends.

Graph answers ``POST /send`` with 202 Accepted. Only a later observation of
the sent message (``isDraft`` false plus a real ``sentDateTime``) proves the
mail was submitted, so every other receipt state stays an unknown outcome the
user can recheck instead of becoming a success.
"""

from __future__ import annotations

from .approval_execution_codec import JSONValue, JournalCodecError, json_mapping

SUBMITTED = "submitted"
NEEDS_REVIEW = "needs_review"
_MESSAGES = {
    SUBMITTED: "Microsoft 365 발송 처리가 확인되었습니다",
    "accepted": "Microsoft 365가 요청을 접수했지만 발송 처리는 아직 확인되지 않았습니다",
    NEEDS_REVIEW: "연결 계정 또는 승인 내용을 확인할 수 없어 검토가 필요합니다",
    "observed_non_draft": "원격 메일이 초안이 아님은 확인했지만 발송 시각은 확인되지 않았습니다",
}
_UNKNOWN_MESSAGE = "현재 원격 발송 상태를 확인할 수 없습니다"


def receipt_state(result: str | None) -> str:
    """The receipt state of one send attempt; anything unreadable is unknown."""
    if not result:
        return "unknown"
    try:
        state = json_mapping(result).get("state")
    except JournalCodecError:
        return "unknown"
    return state if isinstance(state, str) and state else "unknown"


def is_recheckable(state: str) -> bool:
    return state not in {SUBMITTED, NEEDS_REVIEW}


def state_message(state: str) -> str:
    return _MESSAGES.get(state, _UNKNOWN_MESSAGE)


def unconfirmed_response(state: str) -> dict[str, JSONValue]:
    """What an approval reports when a send ran but was not confirmed."""
    recheckable = is_recheckable(state)
    action = (
        "잠시 후 발송 상태를 다시 확인해 주세요"
        if recheckable
        else "Outlook 보낸 편지함에서 실제 발송 내용을 직접 확인해 주세요"
    )
    return {
        "ok": False,
        "error": f"{state_message(state)}. {action}.",
        "state": state,
        "recheckable": recheckable,
        "recoverable": False,
    }
