"""Pure durable-event reduction for workspace reconnect snapshots."""

from __future__ import annotations

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
    "activity.recorded": "activity_logs",
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
    }.get(event.type, "activity")
    decision = event.payload.get("decision")
    default_state = {
        "approval.requested": "action_needed",
        "approval.answered": ("succeeded" if decision == "approve" else "blocked"),
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
            event.payload.get("approval_id")
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
            event.payload.get("status")
            or event.payload.get("decision")
            or event.type.rsplit(".", 1)[-1]
        ),
        "cursor": event.cursor,
        "kind": kind,
        "ui_state": str(event.payload.get("ui_state") or default_state),
    }
    for field in (
        "requester",
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
    ):
        value = event.payload.get(field)
        if isinstance(value, str) and value:
            item[field] = value
    for field in ("computer_sequence",):
        value = event.payload.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            item[field] = value
    focus_preserved = event.payload.get("focus_preserved")
    if isinstance(focus_preserved, bool):
        item["focus_preserved"] = focus_preserved
    return item


def reduce_snapshot(
    session_id: str,
    events: tuple[WorkspaceEvent, ...],
) -> WorkspaceSnapshot:
    conversation: list[dict[str, object]] = []
    panel_items: dict[str, list[dict[str, object]]] = {key: [] for key in PANEL_KEYS}
    active_commands: set[str] = set()
    interrupted = False
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
            conversation.append(
                {
                    "id": event.event_id,
                    "kind": "user_message",
                    "text": text,
                    "actor_id": event.actor_id,
                    "cursor": event.cursor,
                }
            )
        elif event.type == "message.assistant.completed" and isinstance(text, str):
            message: dict[str, object] = {
                "id": event.event_id,
                "kind": "assistant_message",
                "text": text,
                "actor_id": event.actor_id,
                "cursor": event.cursor,
            }
            conversation.append(message)
            panel_items["sessions_history"].append(message)

        panel_key = _PANEL_BY_EVENT.get(event.type)
        if panel_key is not None:
            panel_items[panel_key].append(_panel_item(event))

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
    )
