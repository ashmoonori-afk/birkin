from __future__ import annotations

from pathlib import Path
from typing import cast

from birkin import goals, harness
from birkin.native.session import NativeProjectionSession
from birkin.workspace import WorkspaceService


def test_native_projection_maps_goal_fields_files_and_revision(tmp_path: Path) -> None:
    session_id = "working-native"
    goals.set_goal("Ship native Working Memory", session_id=session_id)
    harness.update_working(
        session_id,
        corrections=["Use canonical state"],
        constraints=["Stay offline"],
        decisions=["Delegate to Python"],
        incomplete=["Render five rows"],
        evidence=["RED captured"],
        next_actions=["Run GREEN"],
    )
    service: WorkspaceService

    def add_evidence(_payload: dict[str, object]) -> dict[str, object]:
        _ = service.emit(
            "evidence.added",
            {
                "evidence_id": "checkpoint-1",
                "summary": "workspace/main.py",
                "path": "/Users/private/workspace/main.py",
                "authorization": "Bearer SEEDED_PUBLIC_SECRET",
            },
        )
        return {}

    service = WorkspaceService(
        root=tmp_path / "workspace",
        session_id=session_id,
        handlers={"memory.link": add_evidence},
    )
    from birkin.workspace import WorkspaceCommand

    command = WorkspaceCommand.parse({
        "protocol_version": 1,
        "command_id": "evidence-1",
        "expected_cursor": 0,
        "type": "memory.link",
        "payload": {},
        "client_context": {"surface": "test", "view_id": "fixture"},
    })
    _ = service.submit(command, actor_id="test:fixture")

    batch = NativeProjectionSession(service, instance_id="instance-1").subscribe(
        after_cursor=0,
        known_instance_id=None,
    )
    assert batch.snapshot is not None
    projected = cast(dict[str, object], batch.snapshot["working_memory"])
    assert projected == {
        "revision": 1,
        "goal": {
            "slug": "ship-native-working-memory",
            "objective": "Ship native Working Memory",
            "tokens_used": 0,
            "status": "active",
        },
        "fields": {
            "corrections": ["Use canonical state"],
            "constraints": ["Stay offline"],
            "decisions": ["Delegate to Python"],
            "incomplete": ["Render five rows"],
            "evidence": ["RED captured"],
            "next_actions": ["Run GREEN"],
        },
        "files_evidence": [
            {
                "id": "checkpoint-1",
                "summary": "workspace/main.py",
                "status": "added",
                "cursor": 3,
                "kind": "evidence",
                "ui_state": "succeeded",
            }
        ],
    }
    rendered = str(batch.snapshot)
    assert "SEEDED_PUBLIC_SECRET" not in rendered
    assert "/Users/private" not in rendered
