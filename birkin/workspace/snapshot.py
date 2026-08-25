"""Pure durable-event reduction for workspace reconnect snapshots."""

from __future__ import annotations

from typing import TypeGuard

from .contracts import REDACTION_MARKER
from .records import (
    PANEL_KEYS,
    ComposerState,
    PanelSummary,
    WorkspaceEvent,
    WorkspaceSnapshot,
    WorkspaceStatus,
)

_PANEL_BY_EVENT = {
    "task.updated": "tasks_runs",
    "run.updated": "tasks_runs",
    "approval.requested": "approvals",
    "approval.answered": "approvals",
    "question.requested": "approvals",
    "question.answered": "approvals",
    "evidence.added": "files_evidence",
    "file.updated": "files_evidence",
    "session.updated": "sessions_history",
    "session.created": "sessions_history",
    "session.selected": "sessions_history",
    "session.renamed": "sessions_history",
    "session.compacted": "sessions_history",
    "activity.recorded": "activity_logs",
    "receipt.recorded": "activity_logs",
    "integrity.warning": "activity_logs",
    "command.completed": "activity_logs",
    "cron.updated": "cron",
    "memory.updated": "memory_skills",
    "skill.updated": "memory_skills",
    "checkpoint.created": "checkpoints_restore",
    "checkpoint.restored": "checkpoints_restore",
    "computer.updated": "computer_use",
    "progress.updated": "activity_logs",
    "tool.started": "activity_logs",
    "tool.completed": "activity_logs",
    "tool.failed": "activity_logs",
    "settings.updated": "settings_status",
    "status.updated": "settings_status",
}


def _panel_item(event: WorkspaceEvent) -> dict[str, object]:
    summary = event.payload.get("summary")
    kind = {
        "task.updated": "task",
        "approval.requested": "approval",
        "approval.answered": "approval",
        "question.requested": "question",
        "question.answered": "question",
        "evidence.added": "evidence",
        "checkpoint.created": "checkpoint",
        "checkpoint.restored": "checkpoint",
        "computer.updated": "computer_use",
        "receipt.recorded": "receipt",
        "command.completed": "receipt",
        "integrity.warning": "integrity_warning",
    }.get(event.type, "activity")
    outcome = event.payload.get("outcome")
    default_state = {
        "approval.requested": "action_needed",
        "approval.answered": (
            "failed"
            if outcome == "failed"
            else "succeeded"
            if outcome in {"approved", "answered_elsewhere"}
            else "blocked"
        ),
        "question.requested": "action_needed",
        "question.answered": "succeeded",
        "task.updated": "running",
        "evidence.added": "succeeded",
        "checkpoint.restored": "succeeded",
        "tool.started": "running",
        "tool.completed": "succeeded",
        "tool.failed": "failed",
        "computer.updated": str(event.payload.get("ui_state") or "pending"),
    }.get(event.type, "pending")
    item: dict[str, object] = {
        "id": str(
            event.event_id
            if event.type == "receipt.recorded"
            else event.payload.get("approval_id")
            or event.payload.get("question_id")
            or event.payload.get("task_id")
            or event.payload.get("evidence_id")
            or event.payload.get("checkpoint_id")
            or event.event_id
        ),
        "summary": (
            summary
            if isinstance(summary, str)
            else str(event.payload.get("name") or event.type)
        ),
        "status": str(
            event.payload.get("outcome")
            or event.payload.get("status")
            or event.payload.get("decision")
            or event.type.rsplit(".", 1)[-1]
        ),
        "cursor": event.cursor,
        "kind": kind,
        "ui_state": str(event.payload.get("ui_state") or default_state),
    }
    for field in (
        "requester",
        "description",
        "category",
        "target",
        "expected_impact",
        "rejection_result",
        "related_evidence",
        "risk",
        "expires_at",
        "receipt_ref",
        "snapshot_ref",
        "effect",
        "refusal_code",
        "session_id",
        "name",
    ):
        value = event.payload.get(field)
        if isinstance(value, str) and value:
            item[field] = value
    if event.type == "receipt.recorded":
        for field in (
            "approval_id",
            "artifact_id",
            "diff_id",
            "job_id",
            "proposal_digest",
            "destination",
        ):
            value = event.payload.get(field)
            if isinstance(value, str) and value:
                item[field] = value
    for field in ("computer_sequence",):
        value = event.payload.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            item[field] = value
    for field in ("sealed", "decided"):
        value = event.payload.get(field)
        if isinstance(value, bool):
            item[field] = value
    if event.type == "approval.answered":
        item["decided"] = True
        receipt = event.payload.get("receipt")
        if isinstance(receipt, str) and receipt:
            item["receipt_ref"] = receipt
    focus_preserved = event.payload.get("focus_preserved")
    if isinstance(focus_preserved, bool):
        item["focus_preserved"] = focus_preserved
    return item


def _reconcile_answered_approval(
    items: list[dict[str, object]],
    resolved: dict[str, object],
) -> None:
    approval_id = resolved["id"]
    replace = {
        "status",
        "cursor",
        "kind",
        "ui_state",
        "decided",
        "receipt_ref",
        "effect",
        "refusal_code",
    }
    for index, current in enumerate(items):
        if current.get("id") != approval_id:
            continue
        merged = dict(current)
        for key in replace:
            if key in resolved:
                merged[key] = resolved[key]
        items[index] = merged
        return
    items.append(resolved)


def _object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _object_mapping(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _live_lease(value: object) -> str | None:
    """A redacted or empty lease is the absence of authority, not a lease."""
    if not isinstance(value, str) or not value or value == REDACTION_MARKER:
        return None
    return value


def reduce_snapshot(
    session_id: str,
    events: tuple[WorkspaceEvent, ...],
) -> WorkspaceSnapshot:
    conversation: list[dict[str, object]] = []
    panel_items: dict[str, list[dict[str, object]]] = {key: [] for key in PANEL_KEYS}
    active_commands: set[str] = set()
    interrupted = False
    terminals: dict[str, dict[str, object]] = {}
    for event in events:
        if event.type == "command.started":
            active_commands.add(event.command_id)
        elif event.type in {"command.completed", "command.failed"}:
            active_commands.discard(event.command_id)
        elif event.type == "turn.interrupted":
            interrupted = True
        elif event.type == "turn.resumed":
            interrupted = False

        text = event.payload.get("text")
        if event.type == "message.user" and isinstance(text, str):
            user_message: dict[str, object] = {
                "id": event.event_id,
                "kind": "user_message",
                "text": text,
                "actor_id": event.actor_id,
                "cursor": event.cursor,
            }
            attachments = event.payload.get("attachments")
            if _object_list(attachments):
                user_message["attachments"] = [
                    dict(item)
                    for item in attachments
                    if _object_mapping(item)
                ]
            conversation.append(user_message)
        elif event.type == "message.assistant.delta" and isinstance(text, str):
            if conversation and conversation[-1].get("kind") == "assistant_stream":
                conversation[-1]["text"] = str(conversation[-1]["text"]) + text
                conversation[-1]["cursor"] = event.cursor
            else:
                conversation.append(
                    {
                        "id": event.event_id,
                        "kind": "assistant_stream",
                        "text": text,
                        "actor_id": event.actor_id,
                        "cursor": event.cursor,
                    }
                )
        elif event.type == "message.assistant.completed" and isinstance(text, str):
            assistant_message: dict[str, object] = {
                "id": event.event_id,
                "kind": "assistant_message",
                "text": text,
                "actor_id": event.actor_id,
                "cursor": event.cursor,
            }
            if conversation and conversation[-1].get("kind") == "assistant_stream":
                conversation[-1] = assistant_message
            else:
                conversation.append(assistant_message)
            panel_items["sessions_history"].append(assistant_message)

        terminal_id = event.payload.get("terminal_id")
        if isinstance(terminal_id, str):
            terminal = terminals.setdefault(
                terminal_id,
                {
                    "terminal_id": terminal_id,
                    "cwd": "",
                    "screen": "",
                    "output_sequence": 0,
                    "state": "unavailable",
                    "exit_status": None,
                    "columns": 80,
                    "rows": 24,
                    "lease": None,
                    "read_only": True,
                },
            )
            if event.type == "terminal.opened":
                terminal.update({
                    "cwd": str(event.payload.get("cwd") or ""),
                    "state": "running",
                    "exit_status": None,
                    "lease": _live_lease(event.payload.get("lease")),
                    "read_only": _live_lease(event.payload.get("lease")) is None,
                })
            elif event.type == "terminal.output":
                data = event.payload.get("data")
                sequence = event.payload.get("sequence")
                if isinstance(data, str):
                    screen = (str(terminal["screen"]) + data).encode("utf-8")
                    terminal["screen"] = screen[-65_536:].decode(
                        "utf-8", errors="replace"
                    )
                if isinstance(sequence, int) and not isinstance(sequence, bool):
                    terminal["output_sequence"] = sequence
            elif event.type == "terminal.resized":
                for key in ("columns", "rows"):
                    value = event.payload.get(key)
                    if isinstance(value, int) and not isinstance(value, bool):
                        terminal[key] = value
            elif event.type == "terminal.exited":
                terminal["state"] = "exited"
                terminal["exit_status"] = event.payload.get("exit_status")
                terminal["lease"] = None
                terminal["read_only"] = True

        panel_key = _PANEL_BY_EVENT.get(event.type)
        if panel_key is not None:
            item = _panel_item(event)
            if event.type == "approval.answered":
                _reconcile_answered_approval(panel_items[panel_key], item)
            else:
                panel_items[panel_key].append(item)

    return WorkspaceSnapshot(
        protocol_version=1,
        session_id=session_id,
        cursor=events[-1].cursor if events else 0,
        panels=tuple(
            PanelSummary(key=key, items=tuple(panel_items[key])) for key in PANEL_KEYS
        ),
        conversation=tuple(conversation),
        composer=ComposerState(
            can_send=not active_commands,
            can_interrupt=bool(active_commands),
            can_resume=interrupted and not active_commands,
        ),
        status=WorkspaceStatus(connection="connected"),
        working_memory={
            "revision": 0,
            "goal": None,
            "fields": {
                "corrections": [],
                "constraints": [],
                "decisions": [],
                "incomplete": [],
                "evidence": [],
                "next_actions": [],
            },
            "files_evidence": list(panel_items["files_evidence"]),
        },
        approval_policy={
            "requested": {"auto_approve": None},
            "effective": {"auto_approve": []},
            "pending_requests": [],
        },
        terminals=tuple(terminals.values()),
    )
