from __future__ import annotations

from pathlib import Path

from birkin.workspace.contracts import ClientContext, WorkspaceCommand
from birkin.workspace.records import CommandReceipt
from birkin.workspace.service import WorkspaceService


def _command(command_id: str, expected_cursor: int) -> WorkspaceCommand:
    return WorkspaceCommand(
        protocol_version=1,
        command_id=command_id,
        expected_cursor=expected_cursor,
        type="test.approval",
        payload={},
        client_context=ClientContext(surface="windows", view_id="main"),
    )


def test_pending_approval_emits_one_redacted_attention_notification(
    tmp_path: Path,
) -> None:
    service = WorkspaceService(
        root=tmp_path / "journal",
        session_id="notification-session",
        handlers={},
    )

    def request_approval(_payload: dict[str, object]) -> dict[str, object]:
        for _ in range(2):
            _ = service.emit(
                "approval.requested",
                {
                    "approval_id": "opaque-approval-1",
                    "summary": "UNTRUSTED customer secret",
                    "description": "UNTRUSTED document contents",
                },
            )
        return {"queued": True}

    service.set_handlers({"test.approval": request_approval})

    receipt: CommandReceipt = service.submit(
        _command("notification-command-1", 0),
        actor_id="windows:main",
    )
    repeated = service.submit(
        _command("notification-command-2", service.snapshot().cursor),
        actor_id="windows:main",
    )

    assert receipt.state == "completed"
    assert repeated.state == "completed"
    notifications = [
        event
        for event in service.events()
        if event.type == "notification.requested"
    ]
    assert len(notifications) == 1
    assert notifications[0].payload == {
        "notification_id": "approval:opaque-approval-1",
        "kind": "approval_waiting",
        "summary": "Birkin에서 승인을 기다리고 있습니다.",
        "body": "앱을 열어 승인 요청을 확인해 주세요.",
        "item_id": "opaque-approval-1",
        "route": "approvals",
        "ui_state": "action_needed",
    }
    serialized = str(notifications[0].payload)
    assert "customer secret" not in serialized
    assert "document contents" not in serialized


def test_activity_progress_history_is_bounded(
    tmp_path: Path,
) -> None:
    service = WorkspaceService(
        root=tmp_path / "journal",
        session_id="bounded-progress-session",
        handlers={},
    )

    def emit_progress(_payload: dict[str, object]) -> dict[str, object]:
        for index in range(120):
            _ = service.emit(
                "progress.updated",
                {
                    "progress_id": "turn:bounded",
                    "summary": f"progress-{index}",
                    "status": "working",
                    "ui_state": "UNTRUSTED" if index == 119 else "pending",
                },
            )
        return {"completed": True}

    service.set_handlers({"test.approval": emit_progress})
    receipt = service.submit(
        _command("bounded-progress-command", 0),
        actor_id="windows:main",
    )

    assert receipt.state == "completed"
    activity = next(
        panel.items
        for panel in service.snapshot().panels
        if panel.key == "activity_logs"
    )
    assert len(activity) == 100
    summaries = [item["summary"] for item in activity]
    assert "progress-0" not in summaries
    assert "progress-119" in summaries
    assert summaries[-1] == "command.completed"
    last_progress = next(
        item for item in activity if item["summary"] == "progress-119"
    )
    assert last_progress["ui_state"] == "pending"
