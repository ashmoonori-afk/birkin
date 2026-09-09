"""Evidence-bound meeting follow-up drafts that require user confirmation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import cast

from .create_content import invalid_content

MAX_NOTES_CHARS = 100_000
MAX_ACTIONS = 500


def meeting_draft_sha256(items: object) -> str:
    if not isinstance(items, list):
        raise invalid_content("meeting draft items must be a list")
    return hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _text(value: object, label: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise invalid_content(f"{label} must be a non-empty string")
    return value.strip()


def review_meeting_actions(notes: object, candidates: object) -> dict[str, object]:
    if not isinstance(notes, str) or not notes.strip() or len(notes) > MAX_NOTES_CHARS:
        raise invalid_content(f"meeting notes must contain 1-{MAX_NOTES_CHARS} characters")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise invalid_content("meeting action candidates must be a list")
    if len(candidates) > MAX_ACTIONS:
        raise invalid_content(f"meeting action candidates exceed {MAX_ACTIONS}")
    items: list[dict[str, object]] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for raw_item in candidates:
        if not isinstance(raw_item, Mapping) or any(not isinstance(key, str) for key in raw_item):
            raise invalid_content("meeting action candidate must be an object")
        item = cast("Mapping[str, object]", raw_item)
        unknown = sorted(set(item) - {"action", "evidence", "assignee", "due_date", "suggested_due_date"})
        if unknown:
            raise invalid_content(f"meeting action candidate has unsupported keys: {unknown}")
        action = cast("str", _text(item.get("action"), "meeting action"))
        evidence = cast("str", _text(item.get("evidence"), "meeting action evidence"))
        if evidence not in notes:
            raise invalid_content("meeting action evidence must be an exact notes substring")
        assignee = _text(item.get("assignee"), "meeting action assignee", optional=True)
        due_date = _text(item.get("due_date"), "meeting action due_date", optional=True)
        suggested = _text(item.get("suggested_due_date"), "suggested due date", optional=True)
        for value, label in ((due_date, "due_date"), (suggested, "suggested_due_date")):
            if value is not None:
                try:
                    _ = date.fromisoformat(value)
                except ValueError as exc:
                    raise invalid_content(f"{label} must be an ISO date") from exc
        key = (action.casefold(), None if assignee is None else assignee.casefold(), due_date)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "action": action,
            "evidence": evidence,
            "assignee": assignee,
            "due_date": due_date,
            "suggested_due_date": suggested,
            "status": "needs_confirmation",
        })
    digest = meeting_draft_sha256(items)
    return {
        "status": "draft",
        "draft_sha256": digest,
        "items": items,
        "confirmation_required": True,
        "persisted": False,
    }


__all__ = ["meeting_draft_sha256", "review_meeting_actions"]
