from __future__ import annotations

import hashlib
import zipfile
from contextlib import nullcontext
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError
from birkin.office.odf_conversion import convert_odf
from birkin.office.odf_package import clone_odf_package, preflight_odf
from birkin.office.odf_types import (
    APPROVED_LIBREOFFICE_VERSION,
    OdfConversionRequest,
    OdfLibreOfficePin,
    OdfLossBudget,
    OdfManifestSecurityConsent,
)

_NS = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
_MEDIA = {
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
}
_FILTERS = {
    "odt": ("writer8", "Office Open XML Text", "docx"),
    "ods": ("calc8", "Calc MS Excel 2007 XML", "xlsx"),
    "odp": ("impress8", "Impress MS PowerPoint 2007 XML", "pptx"),
}


def _manifest(media: str, *, extra: str = "") -> bytes:
    entries = "".join(
        f'<manifest:file-entry manifest:full-path="{name}" manifest:media-type="{kind}"/>'
        for name, kind in (
            ("/", media),
            ("content.xml", "text/xml"),
            ("styles.xml", "text/xml"),
            ("meta.xml", "text/xml"),
            ("settings.xml", "text/xml"),
            ("Pictures/pixel.png", "image/png"),
            ("Object 1/content.xml", "text/xml"),
            ("Scripts/macro.py", "application/binary"),
            ("Basic/Standard/Module1.xml", "text/xml"),
            ("unknown/vendor.bin", "application/octet-stream"),
        )
    )
    return (
        f'<manifest:manifest xmlns:manifest="{_NS}" manifest:version="1.3">'
        f"{entries}{extra}</manifest:manifest>"
    ).encode()


def _odf(path: Path, kind: str = "odt", *, manifest: bytes | None = None) -> Path:
    media = _MEDIA[kind]
    encrypted = (
        '<manifest:file-entry manifest:full-path="secret.bin" '
        'manifest:media-type="application/octet-stream">'
        '<manifest:encryption-data manifest:checksum-type="SHA256"/>'
        "</manifest:file-entry>"
    )
    parts = [
        ("mimetype", media.encode()),
        ("META-INF/manifest.xml", manifest or _manifest(media, extra=encrypted)),
        (
            "content.xml",
            (
                b'<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                b'xmlns:xlink="http://www.w3.org/1999/xlink"><office:a xlink:href="https://example.invalid/x"/></office:document>'
            ),
        ),
        ("styles.xml", b"<styles/>"),
        ("meta.xml", b"<meta/>"),
        ("settings.xml", b"<settings/>"),
        ("Pictures/pixel.png", b"\x89PNG\r\n\x1a\nopaque"),
        ("Object 1/content.xml", b"<object/>"),
        ("Scripts/macro.py", b"print('never execute')"),
        ("Basic/Standard/Module1.xml", b"<module/>"),
        ("unknown/vendor.bin", b"UNKNOWN"),
        ("secret.bin", b"ciphertext"),
        ("META-INF/documentsignatures.xml", b"<signatures/>"),
    ]
    with zipfile.ZipFile(path, "w") as archive:
        for index, (name, payload) in enumerate(parts):
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED if index == 0 else zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return path


@pytest.mark.parametrize("kind", ["odt", "ods", "odp"])
def test_real_odf_identity_manifest_and_security_inventory(tmp_path: Path, kind: str) -> None:
    source = _odf(tmp_path / f"source.{kind}", kind)
    result = preflight_odf(source)

    assert result.format == kind and result.media_type == _MEDIA[kind]
    assert result.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.native_edit_supported is False and result.native_create_supported is False
    roles = {entry.role for entry in result.manifest_entries}
    assert {"core", "media", "embedded_object", "macro", "script", "unknown", "encrypted"} <= roles
    findings = {item.kind for item in result.security_inventory}
    assert {"signature", "macro", "script", "embedded_object", "external_link", "encryption"} <= findings


@pytest.mark.parametrize("fault", ["compressed", "not_first", "wrong_media", "missing_manifest"])
def test_mimetype_and_manifest_package_rules_fail_closed(tmp_path: Path, fault: str) -> None:
    path = tmp_path / "bad.odt"
    media = _MEDIA["odt"]
    with zipfile.ZipFile(path, "w") as archive:
        if fault == "not_first":
            archive.writestr("content.xml", b"<content/>")
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_DEFLATED if fault == "compressed" else zipfile.ZIP_STORED
        archive.writestr(info, ("application/wrong" if fault == "wrong_media" else media).encode())
        if fault != "missing_manifest":
            archive.writestr("META-INF/manifest.xml", _manifest(media))
        if fault != "not_first":
            archive.writestr("content.xml", b"<content/>")
    with pytest.raises(DocumentError):
        _ = preflight_odf(path)


@pytest.mark.parametrize(
    "manifest",
    [
        b"<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>",
        _manifest(_MEDIA["odt"], extra='<manifest:file-entry manifest:full-path="../evil" manifest:media-type="x"/>'),
        _manifest(_MEDIA["odt"], extra='<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'),
        b"<broken",
    ],
)
def test_malformed_dtd_path_duplicate_and_xml_manifests_are_rejected(tmp_path: Path, manifest: bytes) -> None:
    with pytest.raises(DocumentError):
        _ = preflight_odf(_odf(tmp_path / "bad.odt", manifest=manifest))


@pytest.mark.parametrize("entry", ["../escape.xml", "content.xml"])
def test_odf_zip_paths_and_duplicate_parts_are_rejected(tmp_path: Path, entry: str) -> None:
    source = _odf(tmp_path / "unsafe.odt")
    warning_context = pytest.warns(UserWarning) if entry == "content.xml" else nullcontext()
    with warning_context, zipfile.ZipFile(source, "a") as archive:
        archive.writestr(entry, b"<duplicate/>")
    with pytest.raises(DocumentError):
        _ = preflight_odf(source)


def test_exact_clone_preserves_every_byte_and_part_hash(tmp_path: Path) -> None:
    source = _odf(tmp_path / "source.odt")
    output = tmp_path / "clone.odt"
    before = source.read_bytes()
    receipt = clone_odf_package(source, output)
    assert output.read_bytes() == before and source.read_bytes() == before
    assert receipt.exact_byte_clone and receipt.source_sha256 == receipt.output_sha256


def test_unavailable_conversion_is_hash_consent_and_loss_bound_with_no_artifacts(tmp_path: Path) -> None:
    source = _odf(tmp_path / "source.odt")
    output = tmp_path / "output.docx"
    preflight = preflight_odf(source)
    before = source.read_bytes()
    request = OdfConversionRequest(
        target_format="docx",
        source_sha256=preflight.source_sha256,
        engine=OdfLibreOfficePin(APPROVED_LIBREOFFICE_VERSION, "writer8", "Office Open XML Text"),
        loss_budget=OdfLossBudget(preflight.prospective_loss_categories),
        consent=OdfManifestSecurityConsent(
            preflight.source_sha256,
            preflight.manifest_sha256,
            preflight.security_inventory_sha256,
        ),
    )
    receipt = convert_odf(source, output, request)
    assert receipt.status == "refused"
    assert receipt.reason_code == "external_engine_forbidden"
    assert receipt.output is None and not output.exists()
    assert source.read_bytes() == before and set(tmp_path.iterdir()) == {source}


def test_converter_pin_and_loss_budget_are_exact() -> None:
    with pytest.raises(ValueError, match="approved"):
        _ = OdfLibreOfficePin("latest", "writer8", "Office Open XML Text")
    with pytest.raises(ValueError, match="duplicate"):
        _ = OdfLossBudget(("style_layout", "style_layout"))
