"""Supply-chain, security, and production proofs for python-hwpx."""

from __future__ import annotations

import ast
import importlib.metadata
import io
import zipfile
from pathlib import Path

import pytest
from hwpx import HwpxDocument, validate_package
from hwpx.opc.security import HwpxSecurityError, guard_zip_file
from hwpx.opc.xml_utils import parse_xml

from birkin.office.adapters.hwpx import HwpxAdapter
from birkin.office import create_backends
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService
from birkin.office.validation import validate_document


def test_python_hwpx_supply_chain_is_exact_and_python_only() -> None:
    metadata = importlib.metadata.metadata("python-hwpx")
    assert metadata["Version"] == "6.1.0"
    assert metadata["License-Expression"] == "Apache-2.0"
    requirements = importlib.metadata.requires("python-hwpx") or []
    assert "lxml<7,>=4.9" in requirements
    assert all(
        forbidden not in requirement.casefold()
        for requirement in requirements
        for forbidden in ("pywin32", "node", "libreoffice", "pandoc", "unoconv")
    )

    package_root = Path(__import__("hwpx").__file__).resolve().parent
    violations: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = (
                    node.module
                    if isinstance(node, ast.ImportFrom)
                    else node.names[0].name
                )
                if module and module.split(".")[0] in {
                    "subprocess",
                    "requests",
                    "httpx",
                    "urllib3",
                    "socket",
                }:
                    violations.append(f"{path}:{node.lineno}: {module}")
    assert violations == []


def test_python_hwpx_rejects_malicious_zip_and_xml() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.xml", b"must not escape")
    with zipfile.ZipFile(io.BytesIO(payload.getvalue())) as archive:
        with pytest.raises(HwpxSecurityError, match="unsafe ZIP member path"):
            guard_zip_file(archive)

    external_entity = (
        b"<!DOCTYPE root [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>"
        b"<root>&xxe;</root>"
    )
    with pytest.raises(HwpxSecurityError, match="DTD/entity"):
        _ = parse_xml(external_entity)


def test_python_hwpx_blank_create_edit_validate_roundtrip(
    tmp_path: Path,
) -> None:
    result = DocumentService(tmp_path).create_document(
        format="hwpx",
        content={"paragraphs": ["계약 원문 Original contract"]},
        output_name="created.hwpx",
    )
    created = Path(result["draft_artifact"]["uri"])
    assert result["creation_mode"] == "blank_authoring"
    assert validate_package(created).ok is True

    document = HwpxDocument.open(created)
    assert document.text.replace("Original", "Verified") == 1
    edited = tmp_path / "edited.hwpx"
    _ = document.save_to_path(edited)

    assert "Verified contract" in HwpxDocument.open(edited).text.plain()
    assert len(HwpxAdapter().inspect(edited)["sections"]) >= 1
    validation = validate_document(edited, "hwpx")
    assert validation["valid"] is True


def test_forbidden_hwp_automation_packages_are_not_dependencies() -> None:
    project = Path("pyproject.toml").read_text(encoding="utf-8").casefold()
    assert "python-hwpx==6.1.0" in project
    assert "pyhwpx" not in project
    assert "hwpapi" not in project
    assert "pyhwp" not in project


def test_python_hwpx_runtime_rejects_wrong_installed_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        create_backends.importlib.metadata,
        "version",
        lambda _package: "6.0.0",
    )
    monkeypatch.setattr(
        create_backends.importlib,
        "import_module",
        lambda _module: pytest.fail(
            "unsupported python-hwpx was imported before version refusal"
        ),
    )
    with pytest.raises(DocumentError) as caught:
        _ = create_backends.optional_backend("hwpx", "hwpx")
    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert caught.value.details["expected_version"] == "6.1.0"
