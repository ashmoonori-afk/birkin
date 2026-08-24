from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from birkin.office.adapters.docx import DocxAdapter
from birkin.office.adapters.pdf import PdfAdapter
from birkin.office.conversion_audit import LOSS_CATEGORIES
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService
from birkin.office.validation import ValidationResult, validate_document
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
from tests.office.fixture_builders import build_docx_template
from tests.office.test_active_content_consent import _docx
from tests.office.test_hwpx_encryption import _package as encrypted_hwpx
from tests.office.test_hwpx_encryption import _valid_declaration
from tests.office.test_pdf_state_security import _form_pdf, _image_pdf
from tests.symlink_support import create_symlink


def _artifact(path: Path) -> dict[str, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"uri": str(path), "content_hash": digest}


@pytest.mark.parametrize(
    ("name", "payload", "expected"),
    [
        ("scan.pdf", _image_pdf(), ("image_only", "flat_or_no_form")),
        ("xfa.pdf", _form_pdf(xfa=True), ("native_text", "xfa")),
    ],
)
def test_service_pdf_inspect_uses_state_inventory_without_extract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    payload: bytes,
    expected: tuple[str, str],
) -> None:
    source = tmp_path / name
    _ = source.write_bytes(payload)

    def fail_extract(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("service PDF inspection invoked extraction")

    monkeypatch.setattr(PdfAdapter, "extract", fail_extract)
    result = DocumentService(tmp_path).inspect_document(_artifact(source))
    structure = result["structure"]
    assert isinstance(structure, dict)
    inventory = structure["inventory"]
    assert isinstance(inventory, dict)
    assert (inventory["content_type"], inventory["form_type"]) == expected
    assert {"forms", "signatures", "encrypted", "active_content", "risks"} <= set(inventory)
    risks = result["risks"]
    assert isinstance(risks, dict)
    assert "findings" in risks


def test_validate_consumes_verified_snapshot_after_source_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _docx(tmp_path / "source.docx", active=False)
    replacement = tmp_path / "replacement.docx"
    _ = replacement.write_bytes(b"not a package")
    reference = _artifact(source)

    def swap_then_validate(path: Path, format_name: str) -> ValidationResult:
        _ = source.rename(tmp_path / "verified-source.docx")
        create_symlink(source, replacement)
        return validate_document(path, format_name)

    monkeypatch.setattr("birkin.office.service.validate_document", swap_then_validate)
    result = DocumentService(tmp_path).validate_artifact(reference)

    assert result["source_sha256"] == reference["content_hash"]
    assert source.is_symlink()


def test_validate_never_consumes_replaced_snapshot_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = build_docx_template(tmp_path / "source.docx")
    attacker = tmp_path / "attacker.docx"
    _ = attacker.write_bytes(b"attacker package bytes")
    reference = _artifact(source)
    attacker_sha256 = hashlib.sha256(attacker.read_bytes()).hexdigest()
    consumed: list[str] = []

    def replace_then_validate(path: Path, format_name: str) -> ValidationResult:
        snapshots = list(tmp_path.glob(".birkin-read-*.docx"))
        if snapshots:
            try:
                os.replace(attacker, snapshots[0])
            except OSError:
                pass
        consumed.append(hashlib.sha256(path.read_bytes()).hexdigest())
        return validate_document(path, format_name)

    monkeypatch.setattr("birkin.office.service.validate_document", replace_then_validate)
    result = DocumentService(tmp_path).validate_artifact(reference)

    assert consumed == [reference["content_hash"]]
    assert attacker_sha256 not in consumed
    assert result["source_sha256"] == reference["content_hash"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor-path boundary")
def test_validate_uses_unlinked_descriptor_after_snapshot_protection_is_cleared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = build_docx_template(tmp_path / "source.docx")
    attacker = tmp_path / "attacker.docx"
    _ = attacker.write_bytes(b"attacker package bytes")
    reference = _artifact(source)
    consumed: list[str] = []
    formats: list[str] = []
    access_suffixes: list[str] = []
    exposed_names: list[tuple[Path, ...]] = []

    def clear_replace_then_validate(path: Path, format_name: str) -> ValidationResult:
        snapshots = tuple(tmp_path.glob(".birkin-read-*.docx"))
        exposed_names.append(snapshots)
        for snapshot in snapshots:
            if hasattr(os, "chflags"):
                os.chflags(snapshot, 0)
            os.chmod(snapshot, 0o600)
            os.replace(attacker, snapshot)
        consumed.append(hashlib.sha256(path.read_bytes()).hexdigest())
        formats.append(format_name)
        access_suffixes.append(Path(os.fspath(path)).suffix)
        return validate_document(path, format_name)

    monkeypatch.setattr(
        "birkin.office.service.validate_document", clear_replace_then_validate
    )
    result = DocumentService(tmp_path).validate_artifact(reference)

    assert exposed_names == [()]
    assert consumed == [reference["content_hash"]]
    assert formats == ["docx"]
    assert access_suffixes == [""]
    assert result["source_sha256"] == reference["content_hash"]


def test_patch_refuses_drafts_directory_swap_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _docx(tmp_path / "source.docx", active=False)
    service = DocumentService(tmp_path)
    drafts = tmp_path / "artifacts" / "drafts"
    detached = tmp_path / "artifacts" / "detached-drafts"
    original = DocxAdapter.patch_field

    def swap_then_patch(
        self: DocxAdapter,
        source_path: Path,
        output: Path,
        key: str,
        value: str,
        *,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        _ = drafts.rename(detached)
        drafts.mkdir()
        return original(
            self,
            source_path,
            output,
            key,
            value,
            expected_source_sha256=expected_source_sha256,
        )

    monkeypatch.setattr(DocxAdapter, "patch_field", swap_then_patch)
    reference = _artifact(source)
    with pytest.raises(DocumentError) as caught:
        service.apply_document_patch(
            reference,
            {"operations": [{"field": "customer", "value": "Ada"}]},
            expected_source_sha256=reference["content_hash"],
            output_name="draft.docx",
            dry_run=False,
        )

    assert caught.value.code is DocumentErrorCode.PERMISSION_DENIED
    assert not (drafts / "draft.docx").exists()
    assert not (detached / "draft.docx").exists()


EncryptedOperation = Callable[[DocumentService, dict[str, str]], object]


def _encrypted_operations() -> list[tuple[str, EncryptedOperation]]:
    budget = {category: 100 for category in LOSS_CATEGORIES}
    return [
        ("extract", lambda service, artifact: service.extract_document(artifact)),
        ("validate", lambda service, artifact: service.validate_artifact(artifact)),
        (
            "compare",
            lambda service, artifact: service.compare_documents(artifact, artifact),
        ),
        (
            "render",
            lambda service, artifact: service.render_artifact(
                artifact, output_format="structured_preview"
            ),
        ),
        (
            "convert",
            lambda service, artifact: service.convert_document(
                artifact,
                target_format="txt",
                output_name="converted.txt",
                loss_budget=budget,
            ),
        ),
        (
            "patch",
            lambda service, artifact: service.apply_document_patch(
                artifact,
                {"operations": [{"field": "customer", "value": "Ada"}]},
                expected_source_sha256=artifact["content_hash"],
                output_name="patched.hwpx",
                dry_run=True,
            ),
        ),
        (
            "template",
            lambda service, artifact: service.create_document(
                format="hwpx",
                content={"bindings": {"customer": "Ada"}},
                output_name="created.hwpx",
                template=artifact,
            ),
        ),
    ]


@pytest.mark.parametrize(("name", "operation"), _encrypted_operations())
def test_encrypted_hwpx_service_operations_share_typed_refusal_and_leave_no_trace(
    tmp_path: Path, name: str, operation: EncryptedOperation
) -> None:
    source = encrypted_hwpx(tmp_path / "protected.hwpx", _valid_declaration())
    reference = _artifact(source)
    before = source.read_bytes()
    service = DocumentService(tmp_path)

    with pytest.raises(DocumentError) as caught:
        operation(service, reference)

    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE, name
    assert caught.value.details["reason"] == "unsupported_encryption_state", name
    assert source.read_bytes() == before
    assert list((tmp_path / "artifacts" / "drafts").iterdir()) == []
    assert not list(tmp_path.rglob(".birkin-*"))


def test_encrypted_hwpx_tools_share_refusal_while_inspect_remains_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = encrypted_hwpx(tmp_path / "protected.hwpx", _valid_declaration())
    artifact = _artifact(source)
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    registry = build_registry(
        ToolContext(cfg={}, client=None, cwd=tmp_path), include={"documents"}
    )
    payloads: list[tuple[str, dict[str, object]]] = [
        ("extract_document", {"source": artifact}),
        ("validate_artifact", {"artifact": artifact}),
        ("compare_documents", {"left": artifact, "right": artifact}),
        ("render_artifact", {"artifact": artifact, "output_format": "structured_preview"}),
        (
            "office_job_request",
            {
                "request": "Update this HWPX document",
                "source": artifact,
                "outcome": "Set the customer field to Ada",
                "operations": [{"field": "customer", "value": "Ada"}],
                "destination": str(tmp_path / "updated.hwpx"),
            },
        ),
    ]
    for name, payload in payloads:
        result = registry.execute(name, payload)
        assert result.is_error, name
        body = cast("dict[str, object]", json.loads(cast("str", result.content)))
        error = cast("dict[str, object]", body["error"])
        details = cast("dict[str, object]", error["details"])
        assert error["code"] == "CAPABILITY_UNAVAILABLE", name
        assert details["reason"] == "unsupported_encryption_state", name

    inspected = registry.execute("inspect_document", {"source": artifact})
    assert not inspected.is_error
    assert "unsupported_encryption_state" in cast("str", inspected.content)


def test_encrypted_hwpx_inspect_remains_metadata_inventory(tmp_path: Path) -> None:
    source = encrypted_hwpx(tmp_path / "protected.hwpx", _valid_declaration())
    result = DocumentService(tmp_path).inspect_document(_artifact(source))
    structure = result["structure"]
    assert isinstance(structure, dict)
    inventory = structure["inventory"]
    assert isinstance(inventory, dict)
    assert inventory["encryption_state"] == "unsupported_encryption_state"
