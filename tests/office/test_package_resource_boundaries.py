from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.package import preflight_package
from birkin.office.package_types import PackageLimits


def _zip(path: Path, entries: list[tuple[str, bytes]], *, stored: bool = False) -> None:
    compression = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(path, "w", compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return target.getvalue()


def _assert_error(
    path: Path,
    limits: PackageLimits,
    code: DocumentErrorCode,
    reason: str,
) -> None:
    with pytest.raises(DocumentError) as caught:
        _ = preflight_package(path, limits)
    assert caught.value.code is code
    assert caught.value.details["reason"] == reason


@pytest.mark.parametrize(
    ("xml", "limits", "reason"),
    [
        (b"<r>123456789</r>", PackageLimits(max_xml_bytes=10), "xml_bytes"),
        (b"<r><a/><b/></r>", PackageLimits(max_xml_nodes=2), "xml_nodes"),
        (b"<r><a><b/></a></r>", PackageLimits(max_xml_depth=2), "xml_depth"),
        (b'<r a="1" b="2"/>', PackageLimits(max_xml_attributes=1), "xml_attributes"),
        (b"<r>12345</r>", PackageLimits(max_xml_text_bytes=4), "xml_text_bytes"),
    ],
)
def test_xml_parser_resource_limits_are_typed(
    tmp_path: Path,
    xml: bytes,
    limits: PackageLimits,
    reason: str,
) -> None:
    source = tmp_path / "xml.docx"
    _zip(source, [("word/document.xml", xml)])

    _assert_error(source, limits, DocumentErrorCode.LIMIT_EXCEEDED, reason)


def test_media_byte_and_type_limits_are_enforced_from_package_data(tmp_path: Path) -> None:
    source = tmp_path / "media.pptx"
    png = b"\x89PNG\r\n\x1a\n" + b"payload"
    _zip(source, [("ppt/media/image1.png", png)])

    _assert_error(
        source,
        PackageLimits(max_media_bytes=8),
        DocumentErrorCode.LIMIT_EXCEEDED,
        "media_bytes",
    )
    _assert_error(
        source,
        PackageLimits(allowed_media_types=("image/jpeg",)),
        DocumentErrorCode.PACKAGE_INVALID,
        "media_type",
    )


@pytest.mark.parametrize(
    "limits",
    [
        PackageLimits(max_media_width=1),
        PackageLimits(max_media_height=1),
        PackageLimits(max_media_pixels=1),
        PackageLimits(max_media_frames=1),
    ],
)
def test_unavailable_image_metadata_limits_are_explicitly_refused(
    tmp_path: Path,
    limits: PackageLimits,
) -> None:
    source = tmp_path / "image.docx"
    _zip(source, [("word/media/image1.png", b"\x89PNG\r\n\x1a\nsmall")])

    _assert_error(
        source,
        limits,
        DocumentErrorCode.CAPABILITY_UNAVAILABLE,
        "media_metadata",
    )


def test_embedded_packages_obey_explicit_depth_policy(tmp_path: Path) -> None:
    leaf = _zip_bytes([("word/document.xml", b"<r/>")])
    nested = _zip_bytes([("word/embeddings/leaf.docx", leaf)])
    source = tmp_path / "nested.docx"
    _zip(source, [("word/embeddings/nested.docx", nested)])

    _assert_error(
        source,
        PackageLimits(max_package_depth=1),
        DocumentErrorCode.POLICY_DENIED,
        "package_depth",
    )


def test_embedded_package_inflation_counts_toward_cumulative_budget(tmp_path: Path) -> None:
    embedded = _zip_bytes([("payload.bin", b"x" * 20)])
    source = tmp_path / "budget.docx"
    _zip(source, [("word/embeddings/object.docx", embedded)])
    limits = PackageLimits(
        max_package_depth=1,
        max_uncompressed_bytes=len(embedded) + 10,
    )

    _assert_error(
        source,
        limits,
        DocumentErrorCode.LIMIT_EXCEEDED,
        "package_uncompressed_bytes",
    )


def test_crc_is_verified_before_xml_is_trusted_and_leaves_no_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "corrupt.docx"
    malformed = b"<Relationships><Relationship>"
    payload = b"CRC-SENTINEL"
    _zip(
        source,
        [("_rels/.rels", malformed), ("word/document.xml", payload)],
        stored=True,
    )
    raw = source.read_bytes()
    offset = raw.index(payload)
    _ = source.write_bytes(raw[:offset] + bytes([raw[offset] ^ 1]) + raw[offset + 1 :])

    def forbidden_fetch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("preflight attempted network access")

    monkeypatch.setattr("socket.create_connection", forbidden_fetch)
    _assert_error(
        source,
        PackageLimits(),
        DocumentErrorCode.PACKAGE_INVALID,
        "zip_integrity",
    )
    assert set(tmp_path.iterdir()) == {source}
