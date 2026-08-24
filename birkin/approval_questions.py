"""Persistence and resolution boundary for structured approval questions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import actions, config, store


def _pending_path(approval_id: str) -> Path:
    return config.pending_dir() / f"{approval_id}.json"


def request_answers(
    *,
    title: str,
    description: str,
    questions: list[dict[str, Any]],
    origin: str,
    timeout_seconds: int = 300,
    allow_clarification: bool = True,
) -> dict[str, Any]:
    """Persist a channel-neutral action that needs structured answers."""
    normalized = actions.normalize_questions(questions)
    timeout = max(1, min(86_400, int(timeout_seconds)))
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=timeout)
    ).isoformat(timespec="seconds")
    record = store.add_pending(
        category="question",
        title=title,
        description=description,
        payload={},
        origin=origin,
        details={
            "action_state": "action_needed",
            "questions": normalized,
            "allow_clarification": bool(allow_clarification),
            "expires_at": expires_at,
        },
    )
    return {
        "ok": True,
        "event": "action_needed",
        "id": record["id"],
        "questions": normalized,
        "expires_at": expires_at,
    }


def _is_moirai_continuation(approval_id: str) -> bool:
    record = store.get_pending(approval_id)
    envelope = (record or {}).get("continuation")
    return isinstance(envelope, dict) and envelope.get("handler") == "moirai.resume.v1"


def answer(
    approval_id: str,
    *,
    answers: dict[str, Any],
    source: str,
    clarification: str = "",
    navigation: list[str] | None = None,
    capability: str = "",
    resume_token: str = "",
    question_digest: str = "",
    input_schema_version: int | None = None,
    previous_state_digest: str = "",
) -> dict[str, Any]:
    """Resolve one structured action with a validated answer set."""
    from .moirai import continuation, journal

    if (
        _is_moirai_continuation(approval_id)
        or journal.get_input_wait(approval_id) is not None
    ):
        return continuation.accept(
            approval_id,
            answers=answers,
            actor=source,
            capability=capability,
            resume_token=resume_token,
            question_digest=question_digest,
            input_schema_version=input_schema_version,
            previous_state_digest=previous_state_digest,
            clarification=clarification,
            navigation=navigation,
        )
    try:
        with store.file_lock(_pending_path(approval_id)):
            record = store.get_pending(approval_id)
            if (
                not record
                or record.get("status") != "pending"
                or record.get("action_state") != "action_needed"
            ):
                return {
                    "ok": False,
                    "event": "reply_rejected",
                    "id": approval_id,
                    "error": "not found or already resolved",
                }
            expires_at = datetime.fromisoformat(str(record["expires_at"]))
            if expires_at.tzinfo is None:
                raise ValueError("invalid action expiry")
            if expires_at <= datetime.now(timezone.utc):
                store.resolve_pending(
                    approval_id,
                    "expired",
                    details={"action_state": "action_expired"},
                )
                return {
                    "ok": False,
                    "event": "reply_rejected",
                    "id": approval_id,
                    "error": "action expired",
                }
            normalized = actions.normalize_answers(
                record.get("questions") or [], answers
            )
            details: dict[str, Any] = {
                "action_state": "action_resolved",
                "answers": normalized,
                "resolved_by": source,
            }
            if clarification and record.get("allow_clarification"):
                details["clarification"] = clarification[:2_000]
            if navigation:
                details["navigation"] = [str(item)[:64] for item in navigation[-50:]]
            store.resolve_pending(approval_id, "answered", details=details)
    except (actions.InvalidAnswer, KeyError, ValueError) as exc:
        return {
            "ok": False,
            "event": "reply_rejected",
            "id": approval_id,
            "error": str(exc),
        }
    except store.FileLockTimeout:
        return {
            "ok": False,
            "event": "reply_rejected",
            "id": approval_id,
            "error": "action is busy; retry",
        }
    return {
        "ok": True,
        "event": "action_resolved",
        "id": approval_id,
        "answers": normalized,
        "resolved_by": source,
    }
