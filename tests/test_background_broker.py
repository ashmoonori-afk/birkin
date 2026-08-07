from __future__ import annotations

import importlib
import importlib.util
import json
import threading
from pathlib import Path
from types import ModuleType

import pytest


def _background_module() -> ModuleType:
    if importlib.util.find_spec("birkin.background") is None:
        pytest.fail("background broker contract is not implemented")
    return importlib.import_module("birkin.background")


def test_broker_orders_receipts_and_honors_worker_cap(
    tmp_path: Path,
) -> None:
    background = _background_module()
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()

    def first(context):
        context.progress("phase-one")
        first_started.set()
        assert release_first.wait(timeout=2.0)
        return "first-result"

    def second(context):
        context.progress("phase-two")
        second_started.set()
        return "second-result"

    with background.BackgroundBroker(tmp_path, max_workers=1) as broker:
        first_job = broker.submit("first", first)
        assert first_started.wait(timeout=2.0)
        second_job = broker.submit("second", second)
        assert second_started.is_set() is False

        release_first.set()
        first_done = broker.wait(first_job.id, timeout=2.0)
        assert second_started.wait(timeout=2.0)
        second_done = broker.wait(second_job.id, timeout=2.0)

        assert first_done.status == "succeeded"
        assert first_done.result == "first-result"
        assert second_done.status == "succeeded"
        assert second_done.result == "second-result"
        assert [event.sequence for event in first_done.events] == list(
            range(len(first_done.events))
        )
        assert [event.kind for event in first_done.events] == [
            "queued",
            "running",
            "progress",
            "succeeded",
        ]

    receipt = json.loads(
        (tmp_path / f"{first_job.id}.json").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "succeeded"
    assert receipt["result"] == "first-result"
    assert [event["kind"] for event in receipt["events"]] == [
        "queued",
        "running",
        "progress",
        "succeeded",
    ]


def test_broker_cancels_queued_job_without_running_it(
    tmp_path: Path,
) -> None:
    background = _background_module()
    blocker_started = threading.Event()
    release_blocker = threading.Event()
    cancelled_task_started = threading.Event()

    def blocker(context):
        blocker_started.set()
        assert release_blocker.wait(timeout=2.0)
        return "done"

    def cancelled_task(context):
        cancelled_task_started.set()
        return "must-not-run"

    with background.BackgroundBroker(tmp_path, max_workers=1) as broker:
        running = broker.submit("running", blocker)
        assert blocker_started.wait(timeout=2.0)
        queued = broker.submit("queued", cancelled_task)

        assert broker.cancel(queued.id) is True
        release_blocker.set()
        assert broker.wait(running.id, timeout=2.0).status == "succeeded"
        cancelled = broker.wait(queued.id, timeout=2.0)

        assert cancelled.status == "cancelled"
        assert cancelled_task_started.is_set() is False
        assert [event.kind for event in cancelled.events] == [
            "queued",
            "cancelled",
        ]
