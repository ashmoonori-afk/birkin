from __future__ import annotations

from pathlib import Path

import pytest

from birkin.office import export_transaction_receipt
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.export_policy import ExportRequest
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.receipt_auth import sign_receipt
from birkin.office.service import DocumentService
from birkin.office.service_types import ArtifactRef
from birkin.office.service_workspace import DocumentWorkspace


def _draft(service: DocumentService) -> ArtifactRef:
    workspace = DocumentWorkspace(service.home)
    output = workspace.output_path("validated.txt", ".txt")

    def write(target: Path) -> None:
        _ = target.write_text("validated", encoding="utf-8")

    _ = workspace.atomic_publish(output, write)
    return workspace.artifact(output)


def _request(destination: Path) -> ExportRequest:
    return ExportRequest(
        destination=destination,
        actor="reviewer:one",
        proposal_digest="proposal-sha256",
        operations=({"operation": "replace_text", "value": "approved"},),
    )


def _fixture(
    tmp_path: Path,
) -> tuple[DocumentService, ArtifactRef, Path, Path]:
    service = DocumentService(tmp_path / "office-home")
    artifact = _draft(service)
    caller = tmp_path / "caller"
    caller.mkdir()
    return service, artifact, caller, caller / "new.txt"


def test_committed_export_replays_immutable_receipt_window(
    tmp_path: Path,
) -> None:
    service, artifact, caller, destination = _fixture(tmp_path)
    runner = DocumentServiceRunner(service, export_root=caller)
    request = _request(destination)

    first = runner.export(artifact=artifact, request=request)
    second = runner.export(artifact=artifact, request=request)

    assert second["rollback_token"] == first["rollback_token"]
    assert second["issued_at"] == first["issued_at"]
    assert second["expires_at"] == first["expires_at"]
    assert second["receipt_hmac"] == first["receipt_hmac"]


def test_receipt_authentication_failure_precedes_destination_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, artifact, caller, destination = _fixture(tmp_path)

    def fail_signing(*_args: object, **_kwargs: object) -> str:
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            "export_receipt",
            "injected signing failure",
        )

    monkeypatch.setattr(
        export_transaction_receipt,
        "sign_receipt",
        fail_signing,
    )

    with pytest.raises(DocumentError, match="injected signing failure"):
        _ = DocumentServiceRunner(service, export_root=caller).export(
            artifact=artifact,
            request=_request(destination),
        )

    assert not destination.exists()


def test_existing_receipt_never_regenerates_missing_key(
    tmp_path: Path,
) -> None:
    service, artifact, caller, destination = _fixture(tmp_path)
    receipt = DocumentServiceRunner(service, export_root=caller).export(
        artifact=artifact,
        request=_request(destination),
    )
    key = service.home / "receipt_hmac_key"
    key.unlink()

    with pytest.raises(DocumentError) as caught:
        _ = DocumentServiceRunner(
            service,
            export_root=caller,
        ).rollback_export(receipt)

    assert caught.value.retryable is True
    assert not key.exists()
    assert destination.read_text(encoding="utf-8") == "validated"


@pytest.mark.parametrize(
    ("issued_at", "expires_at"),
    [
        ("2099-01-01T00:00:00Z", "2099-01-02T00:00:00Z"),
        ("2020-01-01T00:00:00Z", "2020-02-01T00:00:01Z"),
    ],
)
def test_rollback_rejects_invalid_receipt_window(
    tmp_path: Path,
    issued_at: str,
    expires_at: str,
) -> None:
    service, artifact, caller, destination = _fixture(tmp_path)
    receipt = DocumentServiceRunner(service, export_root=caller).export(
        artifact=artifact,
        request=_request(destination),
    )
    forged = {**receipt, "issued_at": issued_at, "expires_at": expires_at}
    forged["receipt_hmac"] = sign_receipt(
        {
            key: value
            for key, value in forged.items()
            if key != "receipt_hmac"
        },
        service.home,
    )

    with pytest.raises(DocumentError, match="retention window"):
        _ = DocumentServiceRunner(
            service,
            export_root=caller,
        ).rollback_export(forged)
