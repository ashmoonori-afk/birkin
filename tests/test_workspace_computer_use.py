from __future__ import annotations

from pathlib import Path

from birkin.workspace.contracts import ClientContext, WorkspaceCommand
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.service import WorkspaceService
from birkin.workspace.terminal import render_terminal


def _computer_event(
    sequence: int,
    *,
    session_id: str = "workspace-a",
    effect: str = "confirmed",
    approval_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": approval_id is None,
        "effect": effect,
        "receipt_ref": f"sha256:receipt-{sequence}",
        "focus": {"preserved": True},
    }
    if approval_id is not None:
        payload.update(
            {
                "ok": False,
                "effect": "suspected_noop",
                "refusal_code": "background_delivery_unsupported",
                "approval_id": approval_id,
                "review_id": "review-a",
            }
        )
    return {
        "version": 1,
        "sequence": sequence,
        "session_id": session_id,
        "kind": "computer.action.completed",
        "payload": payload,
    }


def _submit_event(
    service: WorkspaceService,
    pending: list[dict[str, object]],
    event: dict[str, object],
    *,
    command_id: str,
) -> None:
    pending.append(event)
    _ = service.submit(
        WorkspaceCommand(
            protocol_version=1,
            command_id=command_id,
            expected_cursor=service.snapshot().cursor,
            type="chat.send",
            payload={"text": "project computer event"},
            client_context=ClientContext(
                surface="terminal",
                view_id="computer-use",
            ),
        ),
        actor_id="terminal:test",
    )


def _harness(
    tmp_path: Path,
) -> tuple[
    WorkspaceService,
    RuntimeWorkspaceAdapter,
    list[dict[str, object]],
]:
    service = WorkspaceService(
        root=tmp_path,
        session_id="workspace-a",
        handlers={},
    )
    adapter = RuntimeWorkspaceAdapter("workspace-a", service.emit)
    pending: list[dict[str, object]] = []

    def handle(_payload: dict[str, object]) -> dict[str, object]:
        adapter.runtime_event("computer_use", pending.pop(0))
        return {}

    service.set_handlers({"chat.send": handle})
    return service, adapter, pending


def test_computer_event_projects_into_replayable_workspace_panel(
    tmp_path: Path,
) -> None:
    service, _adapter, pending = _harness(tmp_path)

    _submit_event(
        service,
        pending,
        _computer_event(1, approval_id="cu_grant_a"),
        command_id="terminal:test:computer-1",
    )

    snapshot = service.snapshot()
    panel = next(item for item in snapshot.panels if item.key == "computer_use")
    assert len(panel.items) == 1
    item = panel.items[0]
    assert item["id"] == "cu_grant_a"
    assert item["summary"] == "컴퓨터 작업에 승인이 필요합니다."
    assert item["status"] == "suspected_noop"
    assert item["kind"] == "computer_use"
    assert item["ui_state"] == "action_needed"
    assert item["receipt_ref"] == "sha256:receipt-1"
    assert item["computer_sequence"] == 1
    assert item["focus_preserved"] is True

    replayed = WorkspaceService(
        root=tmp_path,
        session_id="workspace-a",
        handlers={},
    ).snapshot()
    assert replayed.to_json() == snapshot.to_json()


def test_stale_or_cross_session_computer_overlay_is_rejected(
    tmp_path: Path,
) -> None:
    service, _adapter, pending = _harness(tmp_path)
    _submit_event(
        service,
        pending,
        _computer_event(1),
        command_id="terminal:test:computer-1",
    )
    _submit_event(
        service,
        pending,
        _computer_event(1),
        command_id="terminal:test:computer-stale",
    )
    _submit_event(
        service,
        pending,
        _computer_event(2, session_id="workspace-b"),
        command_id="terminal:test:computer-cross-session",
    )

    panel = next(
        item for item in service.snapshot().panels if item.key == "computer_use"
    )
    assert len(panel.items) == 1


def test_terminal_renders_computer_use_panel_status(tmp_path: Path) -> None:
    service, _adapter, pending = _harness(tmp_path)
    _submit_event(
        service,
        pending,
        _computer_event(1),
        command_id="terminal:test:computer-1",
    )

    lines = render_terminal(
        service.snapshot().to_json(),
        {
            "active_panel": "computer_use",
            "selected_item_id": None,
            "scroll_anchor": 0,
        },
        (90, 30),
    )

    rendered = "\n".join(lines)
    assert "컴퓨터 작업을 완료했습니다." in rendered
    assert "computer.action.completed" not in rendered
