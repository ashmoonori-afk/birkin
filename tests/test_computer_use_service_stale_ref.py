from __future__ import annotations

from pathlib import Path

from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.service import ComputerUseService
from tests.computer_use_fakes import FakeBackend
from tests.test_computer_use_service import _capture, _mutation


def test_service_refuses_old_element_before_delivery(tmp_path: Path) -> None:
    backend = FakeBackend()
    service = ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
    )
    old_capture = _capture(service)
    current_capture = _capture(service)

    result = service.execute(_mutation(old_capture))

    assert current_capture["snapshot_generation"] == 2
    assert result["ok"] is False
    assert result["refusal_code"] == "stale_ref"
    assert result["mutation_dispatched"] is False
    assert backend.mutation_count == 0
