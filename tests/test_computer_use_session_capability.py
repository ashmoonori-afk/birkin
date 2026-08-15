from __future__ import annotations

from pathlib import Path

from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.service import ComputerUseService
from birkin.computer_use.session_policy import SessionCapability
from tests.computer_use_fakes import FakeBackend
from tests.test_computer_use_service import _capture, _mutation


def _service(
    tmp_path: Path,
    capability: SessionCapability,
    backend: FakeBackend | None = None,
) -> ComputerUseService:
    return ComputerUseService(
        backend=backend or FakeBackend(),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
        session_capability=capability,
    )


def test_app_denylist_wins_over_allowlist(tmp_path: Path) -> None:
    capability = SessionCapability(
        session_id="session-a",
        actor="agent",
        source="terminal",
        allowed_operations=frozenset({"type"}),
        allowed_apps=frozenset({"org.birkin.QAFixture"}),
        denied_apps=frozenset({"org.birkin.QAFixture"}),
    )
    service = _service(tmp_path, capability)

    apps = service.execute({"version": 1, "action": "list_apps"})

    assert apps["apps"] == []


def test_empty_app_allowlist_denies_every_app(tmp_path: Path) -> None:
    capability = SessionCapability(
        session_id="session-a",
        actor="agent",
        source="terminal",
        allowed_operations=frozenset({"type"}),
        allowed_apps=frozenset(),
    )
    service = _service(tmp_path, capability)

    apps = service.execute({"version": 1, "action": "list_apps"})

    assert apps["apps"] == []


def test_direct_service_default_denies_every_app(tmp_path: Path) -> None:
    service = ComputerUseService(
        backend=FakeBackend(),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
    )

    apps = service.execute({"version": 1, "action": "list_apps"})

    assert apps["apps"] == []


def test_session_operation_scope_blocks_delivery(tmp_path: Path) -> None:
    capability = SessionCapability(
        session_id="session-a",
        actor="agent",
        source="web",
        allowed_operations=frozenset({"click"}),
    )
    backend = FakeBackend()
    service = _service(tmp_path, capability, backend)
    captured = _capture(service)

    result = service.execute(_mutation(captured))

    assert result["refusal_code"] == "session_capability_denied"
    assert backend.mutation_count == 0


def test_action_receipt_carries_trusted_actor_and_source(
    tmp_path: Path,
) -> None:
    capability = SessionCapability(
        session_id="session-a",
        actor="user-42",
        source="terminal",
        allowed_operations=frozenset({"type"}),
        max_actions=1,
    )
    backend = FakeBackend()
    service = _service(tmp_path, capability, backend)
    first_capture = _capture(service)
    first = service.execute(_mutation(first_capture))
    second_capture = _capture(service)
    second = service.execute(
        _mutation(
            second_capture,
            action_id="action-2",
            idempotency_key="idempotency-2",
        )
    )

    assert first["actor"] == "user-42"
    assert first["source"] == "terminal"
    assert second["ok"] is False
    assert second["refusal_code"] == "rate_limited"
    assert backend.mutation_count == 1
