from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.events import ComputerEvent, EventStream
from birkin.computer_use.reducer import ComputerState, reduce_event
from birkin.computer_use.service import ComputerUseService
from tests.computer_use_fakes import FakeBackend
from tests.test_computer_use_service import _capture, _mutation


def test_typed_events_exclude_raw_typed_input(tmp_path: Path) -> None:
    emitted: list[ComputerEvent] = []
    service = ComputerUseService(
        backend=FakeBackend(),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
        emit=emitted.append,
    )
    captured = _capture(service)
    service.execute(_mutation(captured, value="secret typed value"))

    encoded = json.dumps(
        [event.to_dict() for event in emitted],
        ensure_ascii=False,
    )
    assert "secret typed value" not in encoded
    assert {event.kind for event in emitted} >= {
        "computer.capture.started",
        "computer.capture.completed",
        "computer.action.started",
        "computer.action.completed",
    }
    sequences = [event.sequence for event in emitted]
    assert sequences == list(range(1, len(sequences) + 1))


def test_reducer_replays_capture_artifact_and_receipt_state() -> None:
    events = [
        ComputerEvent(
            version=1,
            sequence=1,
            session_id="session-a",
            kind="computer.capture.completed",
            payload={
                "snapshot_ref": "snapshot-a",
                "artifact": {"ref": "sha256:artifact"},
            },
        ),
        ComputerEvent(
            version=1,
            sequence=2,
            session_id="session-a",
            kind="computer.action.completed",
            payload={
                "receipt_ref": "sha256:receipt",
                "effect": "confirmed",
            },
        ),
    ]

    state = ComputerState()
    for event in events:
        state = reduce_event(state, event)

    assert state.sequence == 2
    assert state.snapshot_ref == "snapshot-a"
    assert state.artifact_refs == ("sha256:artifact",)
    assert state.receipt_refs == ("sha256:receipt",)
    assert state.last_effect == "confirmed"


def test_event_sink_observes_sequence_order_under_concurrency() -> None:
    entered = Event()
    release = Event()
    observed: list[int] = []

    def sink(event: ComputerEvent) -> None:
        observed.append(event.sequence)
        if event.sequence == 1:
            entered.set()
            assert release.wait(timeout=2)

    stream = EventStream(session_id="session-a", emit=sink)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(stream.emit, "first", {})
        assert entered.wait(timeout=2)
        second = executor.submit(stream.emit, "second", {})
        assert observed == [1]
        release.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert observed == [1, 2]


def test_invalid_request_emits_no_started_event(tmp_path: Path) -> None:
    emitted: list[ComputerEvent] = []
    service = ComputerUseService(
        backend=FakeBackend(),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
        emit=emitted.append,
    )

    result = service.execute({"version": 2, "action": "capture"})

    assert result["refusal_code"] == "unsupported_version"
    assert emitted == []
