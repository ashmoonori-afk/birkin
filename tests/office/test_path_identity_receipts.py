# pyright: reportUnusedCallResult=false
from __future__ import annotations

import errno
import hashlib
import os
import subprocess
import sys
import unicodedata
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from birkin.office import path_security
from birkin.office.artifact_identity import verify_descriptor_identity
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service_workspace import DocumentWorkspace


def _ref(path: Path) -> dict[str, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"uri": str(path.absolute()), "content_hash": digest}


def _package(path: Path, kind: str, *, declared: str | None = None) -> Path:
    roots = {
        "docx": "word/document.xml",
        "xlsx": "xl/workbook.xml",
        "pptx": "ppt/presentation.xml",
    }
    media = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        if kind == "hwpx":
            archive.writestr("mimetype", declared or "application/hwp+zip")
            archive.writestr("Contents/section0.xml", "<section/>")
        else:
            content_type = declared or media[kind]
            archive.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                + f'<Override PartName="/{roots[kind]}" ContentType="{content_type}"/></Types>',
            )
            archive.writestr(roots[kind], "<root/>")
    return path


def test_publication_module_import_does_not_require_posix_locking() -> None:
    project_root = Path(__file__).parents[2]
    script = """
import builtins

original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == "fcntl":
        raise ModuleNotFoundError("fcntl is unavailable")
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
import birkin.office.artifact_publication
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_windows_directory_sync_does_not_open_posix_directory_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    identity = path_security.directory_identity(drafts)

    def forbidden_open(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("Windows directory sync must not use POSIX os.open")

    monkeypatch.setattr(os, "open", forbidden_open)
    path_security.sync_directory(drafts, identity, platform="nt")


def test_exact_jail_rejects_outside_traversal_symlink_and_special_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = DocumentWorkspace(home)
    outside = _package(tmp_path / "outside.docx", "docx")
    with pytest.raises(DocumentError) as escaped:
        workspace.resolve_artifact(_ref(outside))
    assert escaped.value.code is DocumentErrorCode.PERMISSION_DENIED

    linked = home / "linked.docx"
    symlink_available = True
    try:
        linked.symlink_to(outside)
    except NotImplementedError:
        symlink_available = False
    except OSError as exc:
        if os.name != "nt" or getattr(exc, "winerror", None) != 1314:
            raise
        symlink_available = False
    if symlink_available:
        with pytest.raises(DocumentError) as symlinked:
            workspace.resolve_artifact(_ref(linked))
        assert symlinked.value.code is DocumentErrorCode.PERMISSION_DENIED
    else:
        assert os.name == "nt" and not linked.exists()

    special = home / "special.docx"
    mkfifo = cast("Callable[[Path], None] | None", getattr(os, "mkfifo", None))
    if mkfifo is not None:
        mkfifo(special)
    else:
        assert os.name == "nt"
        special.mkdir()
    with pytest.raises(DocumentError) as rejected:
        workspace.resolve_artifact({"uri": str(special), "content_hash": "0" * 64})
    assert rejected.value.code is DocumentErrorCode.INVALID_INPUT


@pytest.mark.parametrize("extension", ["docx", "xlsx", "pptx", "hwpx"])
def test_extension_magic_container_and_manifest_must_agree(tmp_path: Path, extension: str) -> None:
    workspace = DocumentWorkspace(tmp_path)
    disguised = tmp_path / f"disguised.{extension}"
    disguised.write_bytes(b"%PDF-1.7\n%%EOF\n")
    with pytest.raises(DocumentError) as magic:
        workspace.resolve_artifact(_ref(disguised))
    assert magic.value.code is DocumentErrorCode.PACKAGE_INVALID

    wrong_kind = "xlsx" if extension == "docx" else "docx"
    if extension in {"pptx", "hwpx"}:
        wrong_kind = "docx"
    mismatched = _package(tmp_path / f"mismatch.{extension}", wrong_kind)
    with pytest.raises(DocumentError) as container:
        workspace.resolve_artifact(_ref(mismatched))
    assert container.value.code is DocumentErrorCode.PACKAGE_INVALID

    malformed = _package(tmp_path / f"manifest.{extension}", extension, declared="application/wrong")
    with pytest.raises(DocumentError) as manifest:
        workspace.resolve_artifact(_ref(malformed))
    assert manifest.value.code is DocumentErrorCode.PACKAGE_INVALID


@pytest.mark.parametrize(
    "manifest",
    [
        b'<Types><Default Extension="xml" ContentType="application/xml"/></Types>',
        (
            b'<Types><x:Override PartName="/word/document.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
        ),
        b'<Types><Override PartName="/word/document.xml"></Types>',
    ],
    ids=["generic-content-type", "unbound-prefix", "malformed-xml"],
)
def test_ooxml_identity_requires_exact_well_formed_main_content_type(
    tmp_path: Path, manifest: bytes
) -> None:
    source = tmp_path / "identity.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", manifest)
        archive.writestr("word/document.xml", b"<document/>")
    before = source.read_bytes()

    with source.open("rb") as stream, pytest.raises(DocumentError) as caught:
        _ = verify_descriptor_identity(stream.fileno(), source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "manifest",
    [
        (
            b'<Types xmlns="urn:not-opc"><Override PartName="/word/document.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
        ),
        (
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types" '
            b'xmlns:x="urn:not-opc"><x:Override PartName="/word/document.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
        ),
        (
            b'<x:Types xmlns:x="urn:not-opc" '
            b'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Override PartName="/word/document.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></x:Types>'
        ),
    ],
    ids=["wrong-namespace", "wrong-override-name", "wrong-root-name"],
)
def test_ooxml_identity_requires_exact_opc_content_types_names(
    tmp_path: Path, manifest: bytes
) -> None:
    source = tmp_path / "namespace.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", manifest)
        archive.writestr("word/document.xml", b"<document/>")
    before = source.read_bytes()

    with source.open("rb") as stream, pytest.raises(DocumentError) as caught:
        _ = verify_descriptor_identity(stream.fileno(), source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert source.read_bytes() == before


def test_source_replacement_during_descriptor_validation_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = DocumentWorkspace(tmp_path)
    source = _package(tmp_path / "source.docx", "docx")
    reference = _ref(source)
    replacement = _package(tmp_path / "replacement.docx", "docx")
    original = verify_descriptor_identity
    replacement_blocked = False

    def replace_after_validation(descriptor: int, path: Path) -> str:
        nonlocal replacement_blocked
        result = original(descriptor, path)
        try:
            os.replace(replacement, source)
        except PermissionError:
            replacement_blocked = True
        return result

    monkeypatch.setattr("birkin.office.service_workspace.verify_descriptor_identity", replace_after_validation)
    try:
        resolved = workspace.resolve_artifact(reference)
    except DocumentError as changed:
        assert not replacement_blocked
        assert changed.code is DocumentErrorCode.SOURCE_CHANGED
    else:
        assert replacement_blocked
        assert resolved == source


def test_pdf_identity_requires_pdf_magic_and_eof(tmp_path: Path) -> None:
    workspace = DocumentWorkspace(tmp_path)
    valid = tmp_path / "valid.pdf"
    valid.write_bytes(b"%PDF-1.7\n1 0 obj\nendobj\n%%EOF\n")
    assert workspace.resolve_artifact(_ref(valid)) == valid
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"%PDF-1.7\ntruncated")
    with pytest.raises(DocumentError):
        workspace.resolve_artifact(_ref(invalid))


def test_output_identity_rejects_same_existing_and_unicode_case_collisions(tmp_path: Path) -> None:
    workspace = DocumentWorkspace(tmp_path)
    existing = workspace.drafts / "Report.PDF"
    existing.write_bytes(b"keep")
    for name in ("report.pdf", unicodedata.normalize("NFD", "résumé.pdf")):
        with pytest.raises(DocumentError):
            workspace.output_path(name, ".pdf")
    with pytest.raises(DocumentError) as same:
        workspace.output_path("Report.PDF", ".pdf")
    assert same.value.code is DocumentErrorCode.OUTPUT_EXISTS
    assert existing.read_bytes() == b"keep"


def test_atomic_publish_validates_fsyncs_and_never_replaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = DocumentWorkspace(tmp_path)
    destination = workspace.output_path("result.pdf", ".pdf")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")

    def write(target: Path) -> None:
        target.write_bytes(b"%PDF-1.7\n%%EOF\n")

    def reject(_target: Path) -> None:
        raise ValueError("invalid")

    with pytest.raises(ValueError):
        workspace.atomic_publish(destination, write, reject)
    assert source.read_bytes() == b"source" and not destination.exists()
    assert not list(workspace.drafts.glob(".birkin-*"))

    destination.write_bytes(b"existing")
    with pytest.raises(DocumentError) as exists:
        workspace.atomic_publish(destination, write)
    assert exists.value.code is DocumentErrorCode.OUTPUT_EXISTS
    assert destination.read_bytes() == b"existing"

    destination.unlink()
    real_fsync = os.fsync
    calls = 0

    def fail_second(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory fsync failed")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_second)
    with pytest.raises(DocumentError):
        workspace.atomic_publish(destination, write)
    assert not destination.exists() and not list(workspace.drafts.glob(".birkin-*"))


def test_write_link_and_directory_replacement_failures_leave_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = DocumentWorkspace(tmp_path)
    destination = workspace.output_path("failure.pdf", ".pdf")

    def fail_write(_target: Path) -> None:
        raise OSError("write failed")

    with pytest.raises(DocumentError):
        workspace.atomic_publish(destination, fail_write)
    assert not destination.exists() and not list(workspace.drafts.glob(".birkin-*"))

    def write(target: Path) -> None:
        target.write_bytes(b"%PDF-1.7\n%%EOF\n")

    def cross_device(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(os, "link", cross_device)
    with pytest.raises(DocumentError):
        workspace.atomic_publish(destination, write)
    assert not destination.exists() and not list(workspace.drafts.glob(".birkin-*"))
    monkeypatch.undo()

    detached = workspace.drafts.with_name("detached-drafts")

    def replace_directory(target: Path) -> None:
        target.write_bytes(b"%PDF-1.7\n%%EOF\n")
        workspace.drafts.rename(detached)
        workspace.drafts.mkdir()

    with pytest.raises(DocumentError) as raced:
        workspace.atomic_publish(destination, replace_directory)
    assert raced.value.code is DocumentErrorCode.PERMISSION_DENIED
    assert not destination.exists() and not list(detached.glob(".birkin-*"))


def test_receipt_digest_is_canonical_and_excludes_nondeterministic_metadata(tmp_path: Path) -> None:
    workspace = DocumentWorkspace(tmp_path)
    first = workspace.receipt_digest({"output_sha256": "a" * 64, "operation": "create"})
    second = workspace.receipt_digest({"operation": "create", "output_sha256": "a" * 64})
    assert first == second
    one = workspace.artifact_receipt({"operation": "create"}, generated_at="now")
    two = workspace.artifact_receipt({"operation": "create"}, generated_at="later")
    assert one["receipt_digest"] == two["receipt_digest"]
    assert one["metadata"] != two["metadata"]

    artifact_path = tmp_path / "stable.pdf"
    artifact_path.write_bytes(b"%PDF-1.7\n%%EOF\n")
    assert workspace.artifact(artifact_path)["artifact_id"] == workspace.artifact(artifact_path)["artifact_id"]
