"""Process-concurrent Telegram owner lease regressions."""

from __future__ import annotations

import json
import multiprocessing
import os
from dataclasses import dataclass
from io import FileIO, TextIOWrapper
from multiprocessing.connection import PipeConnection, wait
from multiprocessing.synchronize import Barrier as BarrierType
from multiprocessing.synchronize import Event as EventType
from pathlib import Path
from threading import BrokenBarrierError
from typing import Protocol
from unittest.mock import patch

import pytest

from birkin.approval_execution_codec import JSONValue
from birkin.gateway.telegram_lease import (
    TelegramGatewayLease,
    TelegramGatewayLeaseRaceError,
    TelegramGatewayOwnedError,
)


class _JsonLoader(Protocol):
    def __call__(self, s: str) -> JSONValue: ...


_load_json: _JsonLoader = json.loads
_TOKEN = "1234567890:concurrent-telegram-lease"
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
class _ContenderContext:
    home: str
    barrier: BarrierType
    release_owner: EventType
    result: PipeConnection


def _acquire_at_publication_barrier(context: _ContenderContext) -> None:
    os.environ["BIRKIN_HOME"] = context.home

    def synchronized_fdopen(
        descriptor: int,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
    ) -> TextIOWrapper:
        _ = buffering
        try:
            _ = context.barrier.wait(timeout=30)
        except BrokenBarrierError:
            context.barrier.abort()
        return TextIOWrapper(FileIO(descriptor, mode), encoding=encoding)
    with patch.object(os, "fdopen", synchronized_fdopen):
        try:
            lease = TelegramGatewayLease.acquire_for_config(_CONFIG)
        except TelegramGatewayOwnedError as error:
            context.result.send(("busy", error.owner_pid, error.fingerprint))
            return
        except (PermissionError, TelegramGatewayLeaseRaceError) as error:
            context.barrier.abort()
            context.result.send(("unexpected", 0, type(error).__name__))
            return

    assert lease is not None
    context.result.send(("owned", lease.owner.pid, lease.fingerprint))
    assert context.release_owner.wait(timeout=30)
    lease.release()
    context.result.send(("released", lease.owner.pid, lease.fingerprint))


def test_simultaneous_processes_publish_exactly_one_complete_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two real processes with complete private records ready to contend.
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    release_owner = context.Event()
    endpoints = [context.Pipe(duplex=False) for _index in range(2)]
    processes = [
        context.Process(
            target=_acquire_at_publication_barrier,
            args=(_ContenderContext(str(tmp_path), barrier, release_owner, sender),),
        )
        for (_receiver, sender) in endpoints
    ]

    # When: both contenders enter the guarded publication transaction.
    for process in processes:
        process.start()
    try:
        for _receiver, sender in endpoints:
            sender.close()
        receivers = [receiver for receiver, _sender in endpoints]
        pending = set(receivers)
        while pending:
            ready = wait(pending, timeout=30)
            assert ready, "lease contender did not report an outcome"
            pending.difference_update(ready)
        results: list[tuple[str, int, str]] = [
            receiver.recv() for receiver in receivers
        ]

        # Then: one owns, every loser is typed busy, and the record is complete.
        assert sorted(result[0] for result in results) == ["busy", "owned"]
        owner_result = next(result for result in results if result[0] == "owned")
        busy_result = next(result for result in results if result[0] == "busy")
        assert busy_result[1:] == owner_result[1:]
        owner_path = next((tmp_path / "gateway-locks").glob("telegram-*.json"))
        owner_record = _load_json(owner_path.read_text(encoding="utf-8"))
        assert isinstance(owner_record, dict)
        assert owner_record["pid"] == owner_result[1]
        assert isinstance(owner_record["process_started_at"], int | float)
        assert isinstance(owner_record["instance_id"], str)
        assert owner_record["instance_id"]

        release_owner.set()
        owner_index = results.index(owner_result)
        receiver, _sender = endpoints[owner_index]
        assert receiver.poll(30), "lease owner did not release"
        assert receiver.recv()[0] == "released"
    finally:
        release_owner.set()
        for process in processes:
            process.join(timeout=30)
            if process.is_alive():
                process.terminate()
                process.join(timeout=30)
        for receiver, sender in endpoints:
            receiver.close()
            sender.close()

    assert all(process.exitcode == 0 for process in processes)
    assert not list((tmp_path / "gateway-locks").glob("telegram-*.json"))

    # Given/When/Then: after release, a later real acquisition succeeds.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    replacement = TelegramGatewayLease.acquire_for_config(_CONFIG)
    assert replacement is not None
    replacement.release()


def test_publication_links_only_a_complete_private_owner_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the no-replace publication primitive is observed at its boundary.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    original_link = os.link
    publications: list[tuple[Path, Path]] = []

    def inspect_link(source: Path, destination: Path) -> None:
        assert not destination.exists()
        record = _load_json(source.read_text(encoding="utf-8"))
        assert isinstance(record, dict)
        assert record["pid"] == os.getpid()
        assert isinstance(record["instance_id"], str) and record["instance_id"]
        publications.append((source, destination))
        original_link(source, destination)

    monkeypatch.setattr(os, "link", inspect_link)

    # When: the lease owner is published.
    lease = TelegramGatewayLease.acquire_for_config(_CONFIG)

    # Then: exactly one complete temp inode was atomically linked to the final path.
    assert lease is not None
    assert len(publications) == 1
    unpublished_path, published_path = publications[0]
    assert published_path == lease.path
    assert unpublished_path != lease.path
    assert not unpublished_path.exists()
    lease.release()


def test_dead_compatible_owner_record_is_recovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an existing-format owner record whose process identity is stale.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    initial = TelegramGatewayLease.acquire_for_config(_CONFIG)
    assert initial is not None
    owner_path = initial.path
    initial.release()
    _ = owner_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "process_started_at": 0.0,
                "instance_id": "dead-compatible-owner",
                "claimed_at": 1.0,
            }
        ),
        encoding="utf-8",
    )

    # When: a new process identity acquires the same token lease.
    replacement = TelegramGatewayLease.acquire_for_config(_CONFIG)

    # Then: the stale compatible owner is replaced and remains releasable.
    assert replacement is not None
    assert replacement.owner.instance_id != "dead-compatible-owner"
    replacement.release()
    assert not owner_path.exists()


def test_unreadable_fresh_owner_is_refused_without_reclamation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a fresh owner pathname that is not yet a readable owner record.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    initial = TelegramGatewayLease.acquire_for_config(_CONFIG)
    assert initial is not None
    owner_path = initial.path
    initial.release()
    _ = owner_path.write_text("{", encoding="utf-8")

    # When/Then: acquisition refuses the race without deleting the fresh path.
    with pytest.raises(TelegramGatewayLeaseRaceError):
        _ = TelegramGatewayLease.acquire_for_config(_CONFIG)
    assert owner_path.read_text(encoding="utf-8") == "{"
