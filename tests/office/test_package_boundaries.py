from __future__ import annotations

import hashlib
import io
import struct
import zipfile
from pathlib import Path

import pytest

from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.limits import PackageLimits
from birkin.office.package import clone_package, preflight_package


def _write_zip(path: Path, entries: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)


def _compressed_payload(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(name)
        with path.open("rb") as package:
            package.seek(info.header_offset)
            header = package.read(30)
            signature, *fields = struct.unpack("<IHHHHHIIIHH", header)
            assert signature == 0x04034B50
            filename_length = fields[-2]
            extra_length = fields[-1]
            package.seek(filename_length + extra_length, 1)
            return package.read(info.compress_size)


@pytest.mark.parametrize(
    ("local_encrypted", "central_encrypted"),
    [(True, False), (False, True)],
)
def test_preflight_rejects_local_and_central_flag_disagreement(
    tmp_path: Path, local_encrypted: bool, central_encrypted: bool
) -> None:
    source = tmp_path / "flags.docx"
    _write_zip(source, [("word/document.xml", b"<document/>")])
    raw = bytearray(source.read_bytes())
    local = raw.index(b"PK\x03\x04")
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<H", raw, local + 6, int(local_encrypted))
    struct.pack_into("<H", raw, central + 8, int(central_encrypted))
    source.write_bytes(raw)
    before = source.read_bytes()

    with pytest.raises(DocumentError) as caught:
        preflight_package(source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert caught.value.details["reason"] == "zip_integrity"
    assert "flags disagree" in caught.value.message
    assert source.read_bytes() == before


@pytest.mark.parametrize("fault", ["compression", "filename"])
def test_preflight_rejects_local_central_header_metadata_disagreement(
    tmp_path: Path, fault: str
) -> None:
    source = tmp_path / "metadata.docx"
    name = "word/document.xml"
    _write_zip(source, [(name, b"<document/>")])
    raw = bytearray(source.read_bytes())
    local = raw.index(b"PK\x03\x04")
    if fault == "compression":
        struct.pack_into("<H", raw, local + 8, zipfile.ZIP_STORED)
    else:
        name_offset = local + 30
        raw[name_offset : name_offset + len(name)] = b"word/evilname.xml"
    source.write_bytes(raw)
    before = source.read_bytes()

    with pytest.raises(DocumentError) as caught:
        preflight_package(source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert caught.value.details["reason"] == "zip_integrity"
    assert "local and central directory" in caught.value.message
    assert source.read_bytes() == before


def _descriptor_zip(path: Path) -> Path:
    class UnseekableBuffer(io.BytesIO):
        def seekable(self) -> bool:
            return False

        def seek(self, *args: object, **kwargs: object) -> int:
            raise io.UnsupportedOperation

    stream = UnseekableBuffer()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"<document/>")
    path.write_bytes(stream.getvalue())
    return path


def test_preflight_accepts_valid_data_descriptor_metadata(tmp_path: Path) -> None:
    source = _descriptor_zip(tmp_path / "descriptor.docx")

    manifest = preflight_package(source)

    assert manifest["parts"]["word/document.xml"]["bytes"] == b"<document/>"


def test_preflight_rejects_data_descriptor_central_metadata_disagreement(
    tmp_path: Path,
) -> None:
    source = _descriptor_zip(tmp_path / "descriptor-mismatch.docx")
    with zipfile.ZipFile(source) as archive:
        info = archive.getinfo("word/document.xml")
        descriptor = info.header_offset + 30 + len(info.filename) + info.compress_size
    raw = bytearray(source.read_bytes())
    assert raw[descriptor : descriptor + 4] == b"PK\x07\x08"
    struct.pack_into("<I", raw, descriptor + 4, 0)
    source.write_bytes(raw)

    with pytest.raises(DocumentError) as caught:
        preflight_package(source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert caught.value.details["reason"] == "zip_integrity"


def test_preflight_rejects_duplicate_normalized_names(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.docx"
    _write_zip(source, [("word/document.xml", b"one"), ("word\\document.xml", b"two")])

    with pytest.raises(DocumentError) as caught:
        preflight_package(source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert "duplicate" in caught.value.message


@pytest.mark.parametrize(
    "entry_name",
    [
        "/word/document.xml",
        "\\word\\document.xml",
        "../document.xml",
        "word/../../document.xml",
        "C:/word/document.xml",
        "//server/share/document.xml",
        "./word/document.xml",
        "word//document.xml",
    ],
)
def test_preflight_rejects_noncanonical_or_absolute_names(
    tmp_path: Path,
    entry_name: str,
) -> None:
    source = tmp_path / "unsafe.docx"
    _write_zip(source, [(entry_name, b"payload")])

    with pytest.raises(DocumentError) as caught:
        preflight_package(source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID


def test_preflight_checks_total_metadata_before_reading_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "expanded.docx"
    _write_zip(source, [("one.bin", b"a" * 6), ("two.bin", b"b" * 6)])
    reads: list[str] = []
    original = zipfile.ZipFile.read

    def recording_read(
        archive: zipfile.ZipFile,
        name: str | zipfile.ZipInfo,
        pwd: bytes | None = None,
    ) -> bytes:
        reads.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
        return original(archive, name, pwd)

    monkeypatch.setattr(zipfile.ZipFile, "read", recording_read)
    limits = PackageLimits(max_entries=10, max_uncompressed_bytes=10, max_entry_ratio=100)

    with pytest.raises(DocumentError) as caught:
        preflight_package(source, limits)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert reads == []


def test_preflight_rejects_malformed_relationships_and_never_fetches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = tmp_path / "malformed.docx"
    _write_zip(malformed, [("_rels/.rels", b"<Relationships><Relationship>")])
    with pytest.raises(DocumentError, match="malformed relationship XML"):
        preflight_package(malformed)

    external = tmp_path / "external.docx"
    _write_zip(
        external,
        [
            (
                "_rels/.rels",
                (
                    b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="attachedTemplate" '
                    b'TargetMode="External" '
                    b'Target="https://example.invalid/template"/></Relationships>'
                ),
            )
        ],
    )

    def forbidden_fetch(*args: object, **kwargs: object) -> None:
        raise AssertionError("relationship scanning attempted a network fetch")

    monkeypatch.setattr("socket.create_connection", forbidden_fetch)
    manifest = preflight_package(external)
    assert manifest["external_relationships"][0]["target"].startswith("https://")


@pytest.mark.parametrize(
    "xml",
    [
        b"<!DOCTYPE document><document/>",
        b"<!DOCTYPE document [<!ENTITY secret 'value'>]><document>&secret;</document>",
        b"<!ENTITY secret 'value'><document/>",
    ],
)
def test_preflight_rejects_dtd_and_entity_declarations(
    tmp_path: Path,
    xml: bytes,
) -> None:
    source = tmp_path / "entity.docx"
    _write_zip(source, [("word/document.xml", xml)])

    with pytest.raises(DocumentError) as caught:
        preflight_package(source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID


def test_clone_preserves_untouched_compressed_payload_and_hash_inventory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.docx"
    opaque = b"opaque-payload-" * 4096
    with zipfile.ZipFile(
        source,
        "w",
        zipfile.ZIP_DEFLATED,
        compresslevel=1,
    ) as archive:
        archive.writestr("word/document.xml", b"<document>old</document>")
        archive.writestr("custom/opaque.bin", opaque)
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    source_payload = _compressed_payload(source, "custom/opaque.bin")
    output = tmp_path / "output.docx"

    source_inventory = clone_package(
        source,
        output,
        {"word/document.xml": b"<document>new</document>"},
    )
    output_inventory = preflight_package(output)

    assert source != output
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest
    assert _compressed_payload(output, "custom/opaque.bin") == source_payload
    assert source_inventory["parts"]["custom/opaque.bin"]["original_sha256"] == hashlib.sha256(opaque).hexdigest()
    assert output_inventory["parts"]["custom/opaque.bin"]["original_sha256"] == source_inventory["parts"]["custom/opaque.bin"]["original_sha256"]
    assert output_inventory["parts"]["word/document.xml"]["original_sha256"] == hashlib.sha256(b"<document>new</document>").hexdigest()
    assert list(tmp_path.glob("*.zip")) == []


def test_clone_refuses_source_as_destination_without_modifying_it(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    _write_zip(source, [("word/document.xml", b"old")])
    before = source.read_bytes()

    with pytest.raises(DocumentError) as caught:
        clone_package(source, source, {"word/document.xml": b"new"})

    assert caught.value.code is DocumentErrorCode.OUTPUT_EXISTS
    assert source.read_bytes() == before
