"""Fixed-copy attention signals derived from canonical workspace events."""

from __future__ import annotations

APPROVAL_NOTIFICATION_SUMMARY = "Birkin에서 승인을 기다리고 있습니다."
APPROVAL_NOTIFICATION_BODY = "앱을 열어 승인 요청을 확인해 주세요."


def approval_waiting_notification(approval_id: str) -> dict[str, object]:
    """Build one redacted notification from an opaque approval identifier."""
    if not approval_id:
        raise ValueError("approval notification requires an opaque item id")
    return {
        "notification_id": f"approval:{approval_id}",
        "kind": "approval_waiting",
        "summary": APPROVAL_NOTIFICATION_SUMMARY,
        "body": APPROVAL_NOTIFICATION_BODY,
        "item_id": approval_id,
        "route": "approvals",
        "ui_state": "action_needed",
    }


__all__ = [
    "APPROVAL_NOTIFICATION_BODY",
    "APPROVAL_NOTIFICATION_SUMMARY",
    "approval_waiting_notification",
]
