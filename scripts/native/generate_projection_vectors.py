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
    with tempfile.TemporaryDirectory(prefix="birkin-native-vectors-") as root:
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
    ]
    factory = NativeMessageFactory(
        instance_id="instance-1",
        server_version="0.4.242",
        command_types=frozenset(),
        session_presets=SESSION_PRESETS,
    )

    working_memory = canonical_working_memory()
    snapshot = public_native_mapping(
        replace(
            reduce_snapshot("session-1", tuple(base_events)),
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
                        reduce_snapshot("session-1", tuple(applied)),
                        working_memory=working_memory,
                    ).to_json()
                ),
            }
        )

    gap = event(11, "message.user", {"text": "must be discarded"})
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


def main() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ = FIXTURE_PATH.write_text(render_fixture(), encoding="utf-8")
    print(f"wrote {FIXTURE_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
