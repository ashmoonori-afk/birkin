"""Durable human-input checkpoints for Moirai workflows."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, NoReturn

from .. import actions, config, store, worker_hooks
from . import bindings, journal

if TYPE_CHECKING:
    from .engine import Run

_WORKER_ID = "main"
_SCHEMA_VERSION = 1


class MoiraiInputRequired(Exception):
    """The source run stopped at a durable human-input checkpoint."""

    def __init__(self, action_id: str) -> None:
        super().__init__(action_id)
        self.action_id = action_id


class ContinuationError(RuntimeError):
    """A bound answer or exact logical resume failed closed."""


def request_input(
    run: "Run",
    *,
    step_id: str,
    title: str,
    description: str,
    questions: list[dict[str, Any]],
    expected_actor: str,
    expected_capability: str,
    timeout_seconds: int = 300,
    allow_clarification: bool = True,
) -> NoReturn | dict[str, Any]:
    """Create a wait or consume the answer assigned to this resumed run."""
    if threading.current_thread() is not threading.main_thread():
        raise ContinuationError(
            "Moirai input checkpoints are only allowed on the main worker"
        )
    normalized = actions.normalize_questions(questions)
    timeout = max(1, min(86_400, int(timeout_seconds)))
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=timeout)
    ).isoformat(timespec="seconds")
    digest = actions.question_digest(
        title=title,
        description=description,
        questions=normalized,
        allow_clarification=bool(allow_clarification),
        input_schema_version=_SCHEMA_VERSION,
    )

    if run.resume_action_id:
        wait = journal.get_input_wait(run.resume_action_id)
        event = journal.get_accepted_answer(run.resume_action_id)
        if wait is None or event is None:
            raise ContinuationError("assigned Moirai input is not durable")
        if (
            wait["run_id"] != run.parent_run_id
            or wait["worker_id"] != _WORKER_ID
            or wait["step_id"] != step_id
            or wait["question_digest"] != digest
            or wait["input_schema_version"] != _SCHEMA_VERSION
        ):
            raise ContinuationError("Moirai input checkpoint contract changed")
        run.consumed_resume_action = True
        return dict(event["input"])

    action_id = uuid.uuid4().hex[:12]
    resume_token = secrets.token_urlsafe(32)
    previous_state_digest = journal.state_digest(
        run.run_id,
        _WORKER_ID,
        step_id,
    )
    request = {
        "title": title,
        "description": description,
        "questions": normalized,
        "allow_clarification": bool(allow_clarification),
    }
    wait = journal.create_input_wait({
        "action_id": action_id,
        "run_id": run.run_id,
        "worker_id": _WORKER_ID,
        "step_id": step_id,
        "request": request,
        "question_digest": digest,
        "expected_actor": expected_actor,
        "expected_capability": expected_capability,
        "expires_at": expires_at,
        "resume_token": resume_token,
        "input_schema_version": _SCHEMA_VERSION,
        "previous_state_digest": previous_state_digest,
    })
    _publish_wait(wait)
    raise MoiraiInputRequired(action_id)


def accept(
    action_id: str,
    *,
    answers: dict[str, Any],
    actor: str,
    capability: str,
    resume_token: str,
    question_digest: str,
    input_schema_version: int | None,
    previous_state_digest: str,
    clarification: str = "",
    navigation: list[str] | None = None,
) -> dict[str, Any]:
    """Validate, append the immutable event, then attempt durable resume."""
    path = config.pending_dir() / f"{action_id}.json"
    try:
        with store.file_lock(path):
            wait = journal.get_input_wait(action_id)
            record = store.get_pending(action_id)
            if (
                wait is None
                or record is None
                or wait["state"] != "waiting"
                or record.get("status") != "pending"
            ):
                return _rejected(action_id, "not found or already resolved")
            rejected = _validate_binding(
                wait,
                actor=actor,
                capability=capability,
                resume_token=resume_token,
                question_digest=question_digest,
                input_schema_version=input_schema_version,
                previous_state_digest=previous_state_digest,
            )
            if rejected:
                return _rejected(action_id, rejected)
            normalized = actions.normalize_answers(
                wait["request"]["questions"],
                answers,
            )
            input_value: dict[str, Any] = {
                "version": _SCHEMA_VERSION,
                "answers": normalized,
                "clarification": (
                    clarification[:2_000]
                    if clarification
                    and wait["request"].get("allow_clarification")
                    else ""
                ),
                "navigation": [
                    str(item)[:64] for item in (navigation or [])[-50:]
                ],
            }
            event = journal.accept_input(
                action_id,
                actual_actor=actor,
                actual_capability=capability,
                resume_token=resume_token,
                input_value=input_value,
            )
            store.resolve_pending(
                action_id,
                "answered",
                details={
                    "action_state": "action_resolved",
                    "answers": normalized,
                    "resolved_by": actor,
                    "resume_state": "queued",
                    "accepted_event_id": event["event_id"],
                },
            )
    except (
        actions.InvalidAnswer,
        journal.ContinuationJournalError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return _rejected(action_id, str(exc))
    except store.FileLockTimeout:
        return _rejected(action_id, "action is busy; retry")

    resume_result: dict[str, Any] | None = None
    try:
        resume_result = resume(action_id)
    except Exception:
        # The accepted event is the durable recovery source. A process restart
        # or later recover() call resumes it; acceptance must not be rolled back.
        pass
    result = {
        "ok": True,
        "event": "action_resolved",
        "id": action_id,
        "answers": normalized,
        "resolved_by": actor,
    }
    if resume_result is not None:
        result["continuation"] = resume_result
    return result


def resume(
    action_id: str,
    *,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    spawn: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Replay the exact durable prefix and inject one accepted input."""
    lock_path = config.pending_dir() / f"{action_id}.resume"
    with store.file_lock(lock_path):
        wait = journal.get_input_wait(action_id)
        event = journal.get_accepted_answer(action_id)
        if wait is None or event is None:
            raise ContinuationError("accepted Moirai input is missing")
        if wait["state"] == "resumed":
            return {
                "ok": True,
                "resume_run_id": wait["resume_run_id"],
                "already_resumed": True,
            }
        child = (
            journal.get_run(str(wait["resume_run_id"]))
            if wait.get("resume_run_id")
            else None
        )
        if (
            wait["state"] == "dispatching"
            and child is not None
            and child.get("status") == "completed"
        ):
            journal.finish_resume(action_id, state="resumed")
            _mark_projection_resumed(action_id, str(child["run_id"]))
            return {
                "ok": True,
                "resume_run_id": child["run_id"],
                "recovered_completed": True,
            }
        source = journal.get_run(wait["run_id"])
        if source is None:
            raise ContinuationError("Moirai continuation source is missing")
        if (
            journal.state_digest(
                wait["run_id"],
                wait["worker_id"],
                wait["step_id"],
            )
            != wait["previous_state_digest"]
        ):
            raise ContinuationError("Moirai continuation state changed")
        script_path = Path(source["script_path"])
        source_text = script_path.read_text(encoding="utf-8")
        if hashlib.sha256(source_text.encode("utf-8")).hexdigest() != source[
            "script_sha256"
        ]:
            raise ContinuationError("Moirai continuation script changed")

        from .engine import load_script_source, run_script

        script = load_script_source(script_path, source_text)
        source_cfg = json.loads(source.get("cfg_json") or "{}")
        stored_specs = json.loads(source.get("bindings_json") or "{}")
        binding_map = bindings.resolve(
            script.roles,
            cli={str(key): str(value) for key, value in stored_specs.items()},
            cfg=source_cfg,
        )
        child_id = wait.get("resume_run_id") or _child_run_id()
        journal.claim_resume(action_id, child_id)
        try:
            outcome = run_script(
                script,
                cfg=source_cfg,
                bindings_map=binding_map,
                args=json.loads(source.get("args_json") or "{}"),
                run_id=child_id,
                resume_from=wait["run_id"],
                parent_run_id=wait["run_id"],
                resume_action_id=action_id,
                on_event=on_event,
                spawn=spawn,
            )
        except Exception as exc:
            journal.finish_resume(action_id, state="error", error=str(exc))
            raise
        journal.finish_resume(action_id, state="resumed")
        _mark_projection_resumed(action_id, outcome["run_id"])
        return {"ok": True, "resume_run_id": outcome["run_id"]}


def recover(
    *,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    spawn: Callable[..., str] | None = None,
) -> list[str]:
    resumed: list[str] = []
    for wait in journal.waiting_inputs():
        if store.get_pending(str(wait["action_id"])) is None:
            _publish_wait(wait)
    for wait in journal.recoverable_inputs():
        try:
            result = resume(
                str(wait["action_id"]),
                on_event=on_event,
                spawn=spawn,
            )
        except Exception:
            continue
        if result.get("ok"):
            resumed.append(str(wait["action_id"]))
    return resumed


def protected_run_ids() -> set[str]:
    return journal.protected_run_ids()


def _validate_binding(
    wait: dict[str, Any],
    *,
    actor: str,
    capability: str,
    resume_token: str,
    question_digest: str,
    input_schema_version: int | None,
    previous_state_digest: str,
) -> str:
    try:
        expires = datetime.fromisoformat(str(wait["expires_at"]))
    except ValueError:
        return "invalid action expiry"
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        return "action expired"
    comparisons = (
        (actor, wait["expected_actor"], "wrong actor"),
        (capability, wait["expected_capability"], "wrong capability"),
        (resume_token, wait["resume_token"], "invalid resume token"),
        (question_digest, wait["question_digest"], "stale question"),
        (
            previous_state_digest,
            wait["previous_state_digest"],
            "stale continuation state",
        ),
    )
    for actual, expected, error in comparisons:
        if not isinstance(actual, str) or not secrets.compare_digest(
            actual,
            str(expected),
        ):
            return error
    if input_schema_version != wait["input_schema_version"]:
        return "unsupported input schema version"
    try:
        current = journal.state_digest(
            wait["run_id"],
            wait["worker_id"],
            wait["step_id"],
        )
    except journal.ContinuationJournalError:
        return "continuation state unavailable"
    if not secrets.compare_digest(current, wait["previous_state_digest"]):
        return "stale continuation state"
    return ""


def _envelope(wait: dict[str, Any]) -> dict[str, Any]:
    value = {
        "schema": 1,
        "handler": "moirai.resume.v1",
        "worker": "moirai",
        "context": {
            key: wait[key]
            for key in (
                "action_id",
                "run_id",
                "worker_id",
                "step_id",
                "question_digest",
                "expected_actor",
                "expected_capability",
                "expires_at",
                "resume_token",
                "input_schema_version",
                "previous_state_digest",
            )
        },
    }
    return worker_hooks.validate(value)


def _publish_wait(wait: dict[str, Any]) -> None:
    request = wait["request"]
    store.add_pending(
        pending_id=str(wait["action_id"]),
        category="question",
        title=str(request["title"]),
        description=str(request["description"]),
        payload={},
        origin=f"moirai:{wait['run_id']}",
        continuation=_envelope(wait),
        details={
            "action_state": "action_needed",
            "questions": request["questions"],
            "allow_clarification": bool(request["allow_clarification"]),
            "expires_at": wait["expires_at"],
            "question_digest": wait["question_digest"],
            "resume_token": wait["resume_token"],
            "input_schema_version": wait["input_schema_version"],
            "previous_state_digest": wait["previous_state_digest"],
            "resume_state": "waiting",
        },
    )


def _mark_projection_resumed(action_id: str, resume_run_id: str) -> None:
    store.resolve_pending(
        action_id,
        "answered",
        details={
            "resume_state": "resumed",
            "resume_run_id": resume_run_id,
        },
    )


def _rejected(action_id: str, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "event": "reply_rejected",
        "id": action_id,
        "error": error,
    }


def _child_run_id() -> str:
    return (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid.uuid4().hex[:4]
    )
