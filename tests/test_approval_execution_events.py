from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from birkin import approval_execution_events
from birkin.approval_execution_codec import canonical, json_mapping


def test_event_frames_are_canonical_for_both_callback_shapes() -> None:
    frames = [
        approval_execution_events.event_frame(
            {"type": "worker_resume", "worker": "odyssey"}
        ),
        approval_execution_events.event_frame(
            "office_progress",
            {"office_phase": "validation", "job_id": "job-1"},
        ),
    ]

    records = []
    for frame in frames:
        assert frame.startswith(approval_execution_events.EVENT_FRAME_PREFIX)
        assert frame.endswith(b"\n")
        payload = frame[len(approval_execution_events.EVENT_FRAME_PREFIX):-1]
        record = json_mapping(payload.decode("utf-8"))
        assert payload == canonical(record)
        records.append(record)

    assert records == [
        {
            "args": [{"type": "worker_resume", "worker": "odyssey"}],
            "kind": "event",
            "version": 1,
        },
        {
            "args": [
                "office_progress",
                {"job_id": "job-1", "office_phase": "validation"},
            ],
            "kind": "event",
            "version": 1,
        },
    ]


def test_stdout_drain_delivers_events_before_helper_continues(
    capsys: pytest.CaptureFixture[str],
) -> None:
    read_fd, write_fd = os.pipe()
    first_observed = threading.Event()
    writer_finished = threading.Event()
    writer_errors: list[str] = []
    events: list[tuple[object, ...]] = []

    def on_event(*args: object) -> None:
        events.append(args)
        if len(events) == 1:
            first_observed.set()

    def write_frames() -> None:
        try:
            _ = os.write(
                write_fd,
                b"executor chatter\n"
                + approval_execution_events.event_frame(
                    {"type": "worker_resume"}
                ),
            )
            if not first_observed.wait(timeout=5):
                writer_errors.append("first event was not drained live")
                return
            _ = os.write(
                write_fd,
                approval_execution_events.event_frame(
                    "office_progress",
                    {"office_phase": "export"},
                ),
            )
        finally:
            os.close(write_fd)
            writer_finished.set()

    writer = threading.Thread(target=write_frames)
    writer.start()
    with os.fdopen(read_fd, "rb", buffering=0) as stream:
        approval_execution_events.drain_helper_stdout(stream, on_event)
    assert writer_finished.wait(timeout=5)
    writer.join(timeout=5)

    assert not writer.is_alive()
    assert writer_errors == []
    assert events == [
        ({"type": "worker_resume"},),
        ("office_progress", {"office_phase": "export"}),
    ]
    assert "stdout: executor chatter" in capsys.readouterr().err


def test_malformed_frames_and_observer_failures_are_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: list[tuple[object, ...]] = []

    def failing_observer(*args: object) -> None:
        observed.append(args)
        raise RuntimeError("observer broke")

    data = (
        approval_execution_events.EVENT_FRAME_PREFIX
        + b"not-json\n"
        + approval_execution_events.event_frame(
            "office_progress",
            {"office_phase": "draft"},
        )
    )
    remaining = approval_execution_events.consume_helper_stdout(
        data[:-2],
        failing_observer,
        final=False,
    )
    assert observed == []

    remaining = approval_execution_events.consume_helper_stdout(
        remaining + data[-2:],
        failing_observer,
        final=True,
    )

    assert remaining == b""
    assert observed == [
        ("office_progress", {"office_phase": "draft"}),
    ]
    diagnostics = capsys.readouterr().err
    assert "malformed event frame" in diagnostics
    assert "event observer failed (RuntimeError): observer broke" in diagnostics


def test_unencodable_event_becomes_a_diagnostic_frame(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    frame = approval_execution_events.event_frame(tmp_path)
    events: list[tuple[object, ...]] = []

    remaining = approval_execution_events.consume_helper_stdout(
        frame,
        lambda *args: events.append(args),
        final=True,
    )

    assert remaining == b""
    assert events == []
    assert "approval event could not be encoded" in capsys.readouterr().err
