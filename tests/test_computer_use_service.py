from __future__ import annotations

from pathlib import Path
from typing import Any

from birkin.computer_use.artifacts import ArtifactStore
from birkin.computer_use.service import ComputerUseService
from tests.computer_use_fakes import FakeBackend, fake_session_capability


def _service(
    tmp_path: Path,
    backend: FakeBackend,
) -> ComputerUseService:
    return ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        session_id="session-a",
        session_capability=fake_session_capability(),
    )


def _capture(
    service: ComputerUseService,
    *,
    mode: str = "ax",
) -> dict[str, Any]:
    apps = service.execute({"version": 1, "action": "list_apps"})
    windows = service.execute(
        {
            "version": 1,
            "action": "list_windows",
            "session_id": apps["session_id"],
            "app_ref": apps["apps"][0]["app_ref"],
        }
    )
    return service.execute(
        {
            "version": 1,
            "action": "capture",
            "session_id": apps["session_id"],
            "mode": mode,
            "target": {"window_ref": windows["windows"][0]["window_ref"]},
        }
    )


def _mutation(
    captured: dict[str, Any],
    *,
    action_id: str = "action-1",
    idempotency_key: str = "idempotency-1",
    value: str = "after",
) -> dict[str, Any]:
    element = captured["elements"][0]
    return {
        "version": 1,
        "action": "type",
        "session_id": captured["session_id"],
        "action_id": action_id,
        "idempotency_key": idempotency_key,
        "target": {
            "app_ref": captured["app_ref"],
            "window_ref": captured["window_ref"],
            "snapshot_ref": captured["snapshot_ref"],
            "element_ref": element["element_ref"],
        },
        "text": value,
        "mode": "replace",
        "delivery": "background",
        "predicted_effect": {
            "property": "value",
            "operation": "equals",
            "value": value,
        },
    }


def test_capture_issues_scoped_opaque_refs_and_artifact(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, FakeBackend())

    captured = _capture(service, mode="som")

    assert captured["ok"] is True
    assert captured["snapshot_generation"] == 1
    assert captured["snapshot_ref"].startswith("cu_snapshot_")
    assert captured["elements"][0]["element_ref"].startswith("cu_element_")
    assert captured["artifact"]["ref"].startswith("sha256:")
    assert "raw_bytes" not in captured["artifact"]


def test_background_mutation_is_confirmed_only_after_readback(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    service = _service(tmp_path, backend)
    captured = _capture(service)

    result = service.execute(_mutation(captured))

    assert result["ok"] is True
    assert result["effect"] == "confirmed"
    assert result["mutation_dispatched"] is True
    assert result["delivery"] == "background"
    assert backend.mutation_count == 1
    assert backend.foreground_count == 0


def test_unverifiable_mutation_is_not_success(tmp_path: Path) -> None:
    backend = FakeBackend()
    service = _service(tmp_path, backend)
    captured = _capture(service)
    backend.readable = False

    result = service.execute(_mutation(captured))

    assert result["ok"] is False
    assert result["effect"] == "unverifiable"
    assert result["refusal_code"] == "verification_unavailable"


def test_verification_response_redacts_observed_text(tmp_path: Path) -> None:
    backend = FakeBackend()
    service = _service(tmp_path, backend)
    captured = _capture(service)

    result = service.execute(_mutation(captured, value="person@example.com"))

    assert result["ok"] is True
    assert result["verification"]["observed"] == "[REDACTED_EMAIL]"


def test_idempotency_returns_receipt_without_redelivery(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    service = _service(tmp_path, backend)
    captured = _capture(service)
    request = _mutation(captured)

    first = service.execute(request)
    second = service.execute(request)
    conflict = service.execute(_mutation(captured, value="different"))

    assert second == first
    assert backend.mutation_count == 1
    assert conflict["ok"] is False
    assert conflict["refusal_code"] == "idempotency_conflict"


def test_oversized_capture_is_a_structured_refusal(tmp_path: Path) -> None:
    backend = FakeBackend()
    service = ComputerUseService(
        backend=backend,
        artifact_store=ArtifactStore(
            tmp_path / "artifacts",
            max_bytes=8,
        ),
        session_id="session-a",
        session_capability=fake_session_capability(),
    )
    apps = service.execute({"version": 1, "action": "list_apps"})
    windows = service.execute(
        {
            "version": 1,
            "action": "list_windows",
            "session_id": service.session_id,
            "app_ref": apps["apps"][0]["app_ref"],
        }
    )

    result = service.execute(
        {
            "version": 1,
            "action": "capture",
            "session_id": service.session_id,
            "mode": "vision",
            "target": {
                "window_ref": windows["windows"][0]["window_ref"],
            },
        }
    )

    assert result["ok"] is False
    assert result["refusal_code"] == "resource_limit"
