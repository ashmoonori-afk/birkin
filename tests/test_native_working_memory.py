from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from birkin import goals, harness
from birkin.native.session import NativeProjectionSession
from birkin.workspace import ProtocolError, WorkspaceCommand, WorkspaceHub, WorkspaceService
from birkin.workspace.contracts import (
    WorkingMemoryBudgetExceeded,
    WorkingMemoryRevisionConflict,
)
from birkin.workspace.working_memory import WorkingMemoryAuthority, WorkingMemoryMutation


def test_native_projection_maps_goal_fields_files_and_revision(tmp_path: Path) -> None:
    session_id = "working-native"
    _ = goals.set_goal("Ship native Working Memory", session_id=session_id)
    _ = harness.update_working(
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


def test_merge_schema_is_strict_and_preview_does_not_persist() -> None:
    malformed: list[object] = [
        None,
        {"op": "merge", "expected_revision": 0},
        {"op": "merge", "expected_revision": 0, "fields": {}, "extra": True},
        {"op": "merge", "expected_revision": True, "fields": {}},
        {"op": "merge", "expected_revision": 0, "fields": {"goal": ["no"]}},
        {"op": "merge", "expected_revision": 0, "fields": {"constraints": "no"}},
        {"op": "merge", "expected_revision": 0, "fields": {"constraints": [1]}},
    ]
    for payload in malformed:
        with pytest.raises(ProtocolError):
            _ = WorkingMemoryMutation.parse(payload)

    authority = WorkingMemoryAuthority("preview-native")
    mutation = WorkingMemoryMutation.parse({
        "op": "merge",
        "expected_revision": 0,
        "fields": {
            "constraints": ["Stay offline", "Stay offline"],
            "decisions": ["Use Python authority"],
        },
    })
    preview = authority.preview(mutation)

    assert preview.requested == {
        "constraints": ["Stay offline", "Stay offline"],
        "decisions": ["Use Python authority"],
    }
    assert preview.effective["constraints"] == ["Stay offline"]
    assert preview.effective["revision"] == 1
    assert harness.working_state("preview-native")["revision"] == 0


def test_memory_merge_delegates_requested_to_effective_transaction(tmp_path: Path) -> None:
    hub = WorkspaceHub(root=tmp_path / "hub", handlers={})
    session, _ = hub.create("merge-native")
    command = WorkspaceCommand.parse({
        "protocol_version": 1,
        "command_id": "merge-1",
        "expected_cursor": 0,
        "type": "memory.write",
        "payload": {
            "op": "merge",
            "expected_revision": 0,
            "fields": {"constraints": ["Offline", "Offline"]},
        },
        "client_context": {"surface": "macos", "view_id": "main"},
    })
    try:
        receipt = hub.submit(command, actor_id="macos:main")
        events = session.events()
        requested = next(event for event in events if event.type == "working_memory.requested")
        updated = next(event for event in events if event.type == "working_memory.updated")

        assert receipt.state == "completed"
        assert cast(dict[str, object], requested.payload["fields"])["constraints"] == [
            "Offline", "Offline"
        ]
        effective = cast(dict[str, object], requested.payload["effective"])
        assert effective["constraints"] == ["Offline"]
        assert updated.payload["working_memory"] == effective
        assert hub.snapshot().working_memory["revision"] == 1
    finally:
        hub.close()


def test_clear_revision_conflict_and_budget_are_canonical() -> None:
    authority = WorkingMemoryAuthority("clear-native")
    merged = authority.apply(WorkingMemoryMutation.parse({
        "op": "merge",
        "expected_revision": 0,
        "fields": {"decisions": ["Temporary"]},
    }))
    assert merged.effective["revision"] == 1

    with pytest.raises(WorkingMemoryRevisionConflict) as stale:
        _ = authority.apply(WorkingMemoryMutation.parse({
            "op": "clear", "expected_revision": 0,
        }))
    assert stale.value.current_revision == 1

    with pytest.raises(ProtocolError):
        _ = WorkingMemoryMutation.parse({
            "op": "clear", "expected_revision": 1, "fields": {},
        })

    clear_mutation = WorkingMemoryMutation.parse({
        "op": "clear", "expected_revision": 1,
    })
    clear_preview = authority.preview(clear_mutation)
    cleared = authority.apply(clear_mutation, preview=clear_preview)
    assert cleared.effective == clear_preview.effective
    assert cleared.effective["revision"] == 2
    assert all(not cleared.effective[field] for field in harness.WORKING_FIELDS)

    with pytest.raises(WorkingMemoryBudgetExceeded) as overflow:
        _ = WorkingMemoryAuthority("budget-native").preview(WorkingMemoryMutation.parse({
            "op": "merge",
            "expected_revision": 0,
            "fields": {
                "evidence": [
                    f"{index}:" + "x" * (harness.WORKING_MAX_ITEM - 8)
                    for index in range(30)
                ]
            },
        }))
    assert overflow.value.limit == harness.WORKING_MAX_RENDER
