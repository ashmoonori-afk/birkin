"""Deterministic stale-owner reclamation concurrency regression."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from contextlib import ExitStack
from dataclasses import dataclass
from multiprocessing.connection import PipeConnection, wait
from multiprocessing.synchronize import Event as EventType
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest

from birkin import store
from birkin.approval_execution_codec import JSONValue
from birkin.gateway.telegram_lease import (
    TelegramGatewayLease,
    TelegramGatewayLeaseRaceError,
    TelegramGatewayOwnedError,
)

_TOKEN = "1234567890:stale-reclamation-aba"
_FINGERPRINT = hashlib.sha256(_TOKEN.encode("utf-8")).hexdigest()[:12]
_CONFIG: dict[str, JSONValue] = {
    "channels": {
        "telegram": {
            "enabled": True,
            "token": _TOKEN,
            "allowed_chat_ids": ["42"],
        }
    }
}


@dataclass(frozen=True, slots=True)
class _ReclaimContext:
    label: Literal["A", "B"]
    home: str
    owner_path: str
    first_reclaimer_ready: EventType
    continue_first_reclaimer: EventType
    release_owner: EventType
    result: PipeConnection


def _reclaim_stale_owner(context: _ReclaimContext) -> None:
    os.environ["BIRKIN_HOME"] = context.home
    owner_path = Path(context.owner_path)
    original_link = os.link
    original_unlink = Path.unlink
    original_file_lock = store.file_lock

    if context.label == "B":
        assert context.first_reclaimer_ready.wait(timeout=30)

    def controlled_unlink(path: Path, missing_ok: bool = False) -> None:
        if context.label == "A" and path == owner_path and not missing_ok:
            context.first_reclaimer_ready.set()
            assert context.continue_first_reclaimer.wait(timeout=30)
        original_unlink(path, missing_ok=missing_ok)

    def observed_link(source: Path, destination: Path) -> None:
        original_link(source, destination)
        if context.label == "B" and destination == owner_path:
            context.continue_first_reclaimer.set()

    def observed_file_lock(
        path: Path,
        *,
        timeout: float = 5.0,
        stale: float = 30.0,
    ) -> store.file_lock:
        if context.label == "B":
            context.continue_first_reclaimer.set()
        return original_file_lock(path, timeout=timeout, stale=stale)

    with ExitStack() as patches:
        _ = patches.enter_context(patch.object(Path, "unlink", controlled_unlink))
        _ = patches.enter_context(patch.object(os, "link", observed_link))
        _ = patches.enter_context(
            patch.object(store, "file_lock", observed_file_lock)
        )
        try:
            lease = TelegramGatewayLease.acquire_for_config(_CONFIG)
        except TelegramGatewayOwnedError as error:
            context.result.send(
                ("busy", context.label, error.owner_pid, error.fingerprint)
            )
            return
        except TelegramGatewayLeaseRaceError as error:
            context.result.send(
                ("unexpected", context.label, 0, type(error).__name__)
            )
            return

    assert lease is not None
    context.result.send(
        ("owned", context.label, lease.owner.pid, lease.fingerprint)
    )
    assert context.release_owner.wait(timeout=30)
    lease.release()
    context.result.send(
        ("released", context.label, lease.owner.pid, lease.fingerprint)
    )


def test_stale_owner_reclamation_is_one_serialized_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: A has parsed one complete dead owner and pauses before reclaiming it.
    lock_root = tmp_path / "gateway-locks"
    lock_root.mkdir()
    owner_path = lock_root / f"telegram-{_FINGERPRINT}.json"
    stale_record = {
        "pid": os.getpid(),
        "process_started_at": 0.0,
        "instance_id": "dead-owner",
        "claimed_at": 1.0,
    }
    _ = owner_path.write_text(json.dumps(stale_record), encoding="utf-8")
    process_context = multiprocessing.get_context("spawn")
    first_reclaimer_ready = process_context.Event()
    continue_first_reclaimer = process_context.Event()
    release_owner = process_context.Event()
    endpoints = [process_context.Pipe(duplex=False) for _index in range(2)]
    processes = [
        process_context.Process(
            target=_reclaim_stale_owner,
            args=(
                _ReclaimContext(
                    label,
                    str(tmp_path),
                    str(owner_path),
                    first_reclaimer_ready,
                    continue_first_reclaimer,
                    release_owner,
                    sender,
                ),
            ),
        )
        for label, (_receiver, sender) in zip(("A", "B"), endpoints, strict=True)
    ]

    # When: B contends while A is paused at the stale-owner unlink boundary.
    for process in processes:
        process.start()
    receivers = [receiver for receiver, _sender in endpoints]
    try:
        for _receiver, sender in endpoints:
            sender.close()
        pending = set(receivers)
        while pending:
            ready = wait(pending, timeout=30)
            assert ready, "stale-owner contender did not report its exact outcome"
            pending.difference_update(ready)
        outcomes: list[tuple[str, str, int, str]] = [
            receiver.recv() for receiver in receivers
        ]

        # Then: the OS guard admits one complete owner and a typed live-owner loser.
        assert sorted(outcome[0] for outcome in outcomes) == ["busy", "owned"]
        winner = next(outcome for outcome in outcomes if outcome[0] == "owned")
        loser = next(outcome for outcome in outcomes if outcome[0] == "busy")
        assert loser[2:] == winner[2:]
        published = json.loads(owner_path.read_text(encoding="utf-8"))
        assert published["pid"] == winner[2]
        assert isinstance(published["process_started_at"], int | float)
        assert isinstance(published["instance_id"], str)
        assert published["instance_id"]

        release_owner.set()
        winner_receiver = receivers[outcomes.index(winner)]
        assert wait([winner_receiver], timeout=30) == [winner_receiver]
        assert winner_receiver.recv()[0] == "released"
    finally:
        release_owner.set()
        exited = set(wait([process.sentinel for process in processes], timeout=30))
        for process in processes:
            if process.sentinel not in exited:
                process.terminate()
            process.join(timeout=30)
        for receiver, sender in endpoints:
            receiver.close()
            sender.close()

    assert all(process.exitcode == 0 for process in processes)
    assert not owner_path.exists()

    # Given/When/Then: release permits reacquisition and leaves only its OS lock inode.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    replacement = TelegramGatewayLease.acquire_for_config(_CONFIG)
    assert replacement is not None
    replacement.release()
    assert not list(lock_root.glob("*.tmp"))
    guard_paths = list(lock_root.glob("*.lock"))
    assert len(guard_paths) == 1
    assert guard_paths[0].parent == lock_root
    assert _FINGERPRINT in guard_paths[0].name
    assert _TOKEN not in str(guard_paths[0])


@pytest.mark.parametrize(
    "lock_error",
    [store.FileLockTimeout(), PermissionError()],
    ids=("timeout", "os-contention"),
)
def test_guard_acquisition_failures_are_typed_lease_races(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lock_error: OSError,
) -> None:
    # Given: the OS advisory-lock boundary refuses this contender.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    def refuse_lock(_path: Path) -> store.file_lock:
        raise lock_error

    monkeypatch.setattr(store, "file_lock", refuse_lock)

    # When/Then: acquisition exposes only the established typed race error.
    with pytest.raises(TelegramGatewayLeaseRaceError) as caught:
        _ = TelegramGatewayLease.acquire_for_config(_CONFIG)
    assert caught.value.__cause__ is lock_error
    assert not list((tmp_path / "gateway-locks").glob("*.json"))
