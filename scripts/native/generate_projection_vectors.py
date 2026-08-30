"""Generate Swift reducer vectors from Birkin's canonical Python projection.

Usage (from the repository root)::

    uv run python scripts/native/generate_projection_vectors.py
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from birkin import goals
from birkin import __version__
from birkin.native.messages import NativeMessageFactory
from birkin.native.projection import public_native_mapping, public_workspace_event
from birkin.native.protocol import NativeEnvelope, decode_frame, encode_frame
from birkin.workspace.presets import SESSION_PRESETS
from birkin.workspace.records import WorkspaceEvent
from birkin.workspace.snapshot import reduce_snapshot
from birkin.workspace.working_memory import (
    WorkingMemoryAuthority,
    WorkingMemoryMutation,
    project_working_memory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPO_ROOT
    / "macos"
    / "BirkinNativeApp"
    / "Tests"
    / "BirkinNativeProtocolTests"
    / "GoldenVectors"
    / "native-projection-vectors.json"
)


def event(cursor: int, event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
    return WorkspaceEvent(
        protocol_version=1,
        session_id="session-1",
        cursor=cursor,
        event_id=f"event-{cursor}",
        type=event_type,
        timestamp=f"2026-08-20T12:00:{cursor:02d}Z",
        actor_id="macos:window-main",
        command_id="command-1",
        payload=payload,
    )


def frame_document(envelope: NativeEnvelope) -> dict[str, object]:
    frame = encode_frame(envelope)
    decoded = decode_frame(frame)
    return {
        "frame_base64": base64.b64encode(frame).decode("ascii"),
        "frame_byte_count": len(frame),
        "kind": decoded.kind,
    }


def canonical_working_memory() -> dict[str, object]:
    """Build deterministic fixture data through the real Python authorities."""

    previous_home = os.environ.get("BIRKIN_HOME")
    with tempfile.TemporaryDirectory(
        prefix="birkin-native-vectors-",
        dir=Path.home(),
    ) as root:
        os.environ["BIRKIN_HOME"] = root
        try:
            _ = goals.set_goal("Ship native Working Memory", session_id="session-1")
            authority = WorkingMemoryAuthority("session-1")
            _ = authority.apply(WorkingMemoryMutation.parse({
                "op": "merge",
                "expected_revision": 0,
                "fields": {
                    "corrections": ["Use canonical state"],
                    "constraints": ["Stay offline"],
                    "decisions": ["Delegate to Python"],
                    "incomplete": ["Render five rows"],
                    "evidence": ["RED captured"],
                    "next_actions": ["Run GREEN"],
                },
            }))
            return project_working_memory(
                "session-1",
                ({
                    "id": "checkpoint-1",
                    "summary": "workspace/main.py",
                    "path": "/private/workspace/main.py",
                    "kind": "evidence",
                },),
            )
        finally:
            if previous_home is None:
                del os.environ["BIRKIN_HOME"]
            else:
                os.environ["BIRKIN_HOME"] = previous_home


def render_fixture() -> str:
    """Render snapshot and delta vectors through production projection code."""

    base_events = [
        event(1, "message.user", {"text": "Ship the reducer"}),
        event(2, "message.assistant.completed", {"text": "Snapshot ready"}),
    ]
    delta_events = [
        event(
            3,
            "task.updated",
            {"task_id": "task-1", "summary": "Canonical reducer", "status": "running"},
        ),
        event(4, "command.started", {"command_type": "chat.send"}),
        event(5, "message.user", {"text": "Continue in cursor order"}),
        event(6, "message.assistant.delta", {"text": "Events "}),
        event(7, "message.assistant.delta", {"text": "reduced"}),
        event(8, "message.assistant.completed", {"text": "Events reduced"}),
        event(9, "command.completed", {"command_type": "chat.send"}),
        event(10, "terminal.opened", {
            "terminal_id": "terminal-vector",
            "session_id": "session-1",
            "actor_kind": "native_human",
            "cwd": "/private/workspace",
            "shell": "/bin/sh",
            "pid": 4242,
            "lease": "vector-lease",
            "lease_expires_in": 60.0,
            "approval_id": "approval-vector",
            "state": "running",
        }),
        event(11, "terminal.output", {
            "terminal_id": "terminal-vector",
            "sequence": 1,
            "data": "hello-native\r\n",
        }),
        event(12, "terminal.resized", {
            "terminal_id": "terminal-vector", "columns": 100, "rows": 30,
        }),
        event(13, "terminal.exited", {
            "terminal_id": "terminal-vector", "exit_status": 0, "reason": "closed",
        }),
        event(14, "receipt.recorded", {
            "receipt_ref": "receipt:command-1", "summary": "Command completed",
        }),
        event(15, "integrity.warning", {
            "summary": "Interrupted receipt sealed", "status": "warning",
        }),
        event(16, "approval.requested", {
            "approval_id": "approval-vector", "summary": "Save reviewed workbook",
            "description": "Comparison!A1: 7 to 9", "category": "office_job",
            "status": "pending", "risk": "high", "sealed": True,
            "decided": False,
            "source_filename": "comparison-source.xlsx",
            "destination": "/workspace/approved/comparison.xlsx",
            "overwrite_approved": False,
            "authority_digest": "a" * 64,
            "requester": "native:session-1",
            "rejection_result": "Rejecting leaves the source unchanged and writes no output.",
        }),
        event(17, "approval.answered", {
            "approval_id": "approval-vector", "decision": "approve",
            "outcome": "approved", "receipt": "receipt:approval-vector",
        }),
        event(18, "approval.requested", {
            "approval_id": "approval-refused",
            "summary": "Save while authority is unavailable",
            "category": "office_job", "status": "pending", "risk": "high",
            "sealed": True, "decided": False,
        }),
        event(19, "approval.answered", {
            "approval_id": "approval-refused", "decision": "approve",
            "outcome": "rejected_by_authority",
        }),
        event(20, "approval.requested", {
            "approval_id": "approval-elsewhere",
            "summary": "Save answered by another reviewer",
            "category": "office_job", "status": "pending", "risk": "high",
            "sealed": True, "decided": False,
        }),
        event(21, "approval.answered", {
            "approval_id": "approval-elsewhere", "decision": "approve",
            "outcome": "answered_elsewhere",
        }),
        event(22, "progress.updated", {
            "progress_id": "turn:session-1",
            "summary": "응답을 준비하고 있습니다.",
            "status": "working",
            "ui_state": "pending",
        }),
        event(23, "notification.requested", {
            "notification_id": "approval:approval-1",
            "kind": "approval_waiting",
            "summary": "Birkin에서 승인을 기다리고 있습니다.",
            "body": "앱을 열어 승인 요청을 확인해 주세요.",
            "item_id": "approval-1",
            "route": "approvals",
            "ui_state": "action_needed",
        }),
        event(24, "progress.updated", {
            "progress_id": "turn:session-1",
            "summary": "응답을 완료했습니다.",
            "status": "succeeded",
            "ui_state": "succeeded",
        }),
    ]
    factory = NativeMessageFactory(
        instance_id="instance-1",
        server_version=__version__,
        session_id="session-1",
        command_types=frozenset(),
        session_presets=SESSION_PRESETS,
    )

    working_memory = canonical_working_memory()
    snapshot = public_native_mapping(
        replace(
            reduce_snapshot(
                "session-1", tuple(_as_client_sees(item) for item in base_events)
            ),
            working_memory=working_memory,
        ).to_json()
    )
    snapshot_body = dict(snapshot)
    snapshot_body.update({"instance_id": "instance-1", "reset_reason": "initial"})
    snapshot_message = factory.message("snapshot", body=snapshot_body)

    applied = list(base_events)
    event_vectors: list[dict[str, object]] = []
    for delta in delta_events:
        applied.append(delta)
        message = factory.message("event", body=public_workspace_event(delta))
        event_vectors.append(
            {
                **frame_document(message),
                "cursor": delta.cursor,
                "expected_state": public_native_mapping(
                    replace(
                        reduce_snapshot(
                            "session-1",
                            tuple(_as_client_sees(item) for item in applied),
                        ),
                        working_memory=working_memory,
                    ).to_json()
                ),
            }
        )

    gap = event(applied[-1].cursor + 2, "message.user", {"text": "must be discarded"})
    gap_message = factory.message("event", body=public_workspace_event(gap))
    document = {
        "generated_by": "scripts/native/generate_projection_vectors.py",
        "source_modules": [
            "birkin.native.messages.NativeMessageFactory",
            "birkin.native.projection.public_native_mapping",
            "birkin.native.projection.public_workspace_event",
            "birkin.workspace.snapshot.reduce_snapshot",
            "birkin.workspace.working_memory.WorkingMemoryAuthority",
            "birkin.workspace.working_memory.project_working_memory",
            "birkin.goals.GoalState",
        ],
        "snapshot": {
            **frame_document(snapshot_message),
            "expected_state": snapshot,
        },
        "events": event_vectors,
        "gap_event": {**frame_document(gap_message), "cursor": gap.cursor},
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"



def _as_client_sees(event: WorkspaceEvent) -> WorkspaceEvent:
    """The event a client actually reduces: the public, redacted projection."""
    public = public_workspace_event(event)
    payload = public["payload"]
    assert isinstance(payload, dict)
    return replace(event, payload=payload)


def main() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ = FIXTURE_PATH.write_text(render_fixture(), encoding="utf-8")
    print(f"wrote {FIXTURE_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
