from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.cancellation import CancellationRegistry
from birkin.computer_use.service import ComputerUseService
from tests.computer_use_fakes import FakeBackend
from tests.test_computer_use_service import _capture, _mutation


def _service(
    tmp_path: Path,
    backend: FakeBackend,
) -> ComputerUseService:
    return ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
    )


def test_cancel_before_delivery_has_no_effect(tmp_path: Path) -> None:
    backend = FakeBackend()
    service = _service(tmp_path, backend)
    captured = _capture(service)
    service.cancel("action-1")

    result = service.execute(_mutation(captured))

    assert result["status"] == "cancelled"
    assert result["mutation_dispatched"] is False
    assert backend.mutation_count == 0


def test_cancel_during_delivery_returns_unknown_effect(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.block_mutation = True
    service = _service(tmp_path, backend)
    captured = _capture(service)
    request = _mutation(captured)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.execute, request)
        assert backend.mutation_started.wait(timeout=2)
        service.cancel("action-1")
        backend.mutation_continue.set()
        result = future.result(timeout=2)

    assert result["ok"] is False
    assert result["effect"] == "unverifiable"
    assert result["refusal_code"] == "unknown_effect"
    assert result["mutation_dispatched"] is True
    assert backend.mutation_count == 1


def test_cancellation_capacity_never_resurrects_older_action() -> None:
    registry = CancellationRegistry(max_entries=2)

    assert registry.cancel("action-1") is True
    assert registry.cancel("action-2") is True
    assert registry.cancel("action-3") is False
    assert registry.is_cancelled("action-1") is True
    assert registry.is_cancelled("action-3") is False
