from __future__ import annotations

import base64
import hashlib
import struct
import zipfile
from pathlib import Path
from typing import cast

import pytest

from birkin.office.adapters.hwpx import HwpxAdapter
from birkin.office.adapters.hwpx_types import ParagraphLocator
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService

_NS = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
_AES256 = "http://www.w3.org/2001/04/xmlenc#aes256-cbc"
_PBKDF2 = f"{_NS}#pbkdf2"
_SHA256_1K = f"{_NS}#sha256-1k"
_SHA256 = "http://www.w3.org/2000/09/xmldsig#sha256"
_SALT = bytes(range(16))
_IV = bytes(range(16, 32))
_PLAIN = (
    b'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    b'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
    b'<hp:p id="secret"><hp:run><hp:t>classified</hp:t></hp:run></hp:p></hs:sec>'
)
# Generated once from Hancom's published profile: SHA-256(password), then
# PBKDF2-HMAC-SHA1/1024 and AES-256-CBC over space-padded _PLAIN.
_CIPHERTEXT_SEGMENTS = (
    "QCxA1o4PrSc7XaS6QPfQ7Vow7ifm05TdQu2nTEsKe0BQdXhb9m5d1qOVb4s6CRch",
    "slbSdj0o41q3kbINpzUbRFuWnZWSw9cjxD+SyEwbCFD1BPu7BsadllK9mVrtixVo",
    "mS4t1+efiEjGhFP1qeS0ohM9nvDvHLpcfVFLXFbLRiNdLOnvttFv2wW8lcKo3goq",
    "x4Lp1k7oEr9aoTCkDjvtM/2kn9lVf4Ryt+tmmHDNtkfutYqVhAZiYFXNIF0S8TUW",
)
_CIPHERTEXT = base64.b64decode("".join(_CIPHERTEXT_SEGMENTS))


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _entry(
    target: str,
    plain: bytes,
    *,
    algorithm: str = _AES256,
    salt: str | None = None,
) -> str:
    salt_value = _b64(_SALT) if salt is None else salt
    return f'''<manifest:file-entry manifest:full-path="{target}" manifest:media-type="application/xml" manifest:size="{len(plain)}">
 <manifest:encryption-data manifest:checksum-type="{_SHA256_1K}" manifest:checksum="{_b64(hashlib.sha256(plain[:1024]).digest())}">
  <manifest:algorithm manifest:algorithm-name="{algorithm}" manifest:initialisation-vector="{_b64(_IV)}"/>
  <manifest:key-derivation manifest:key-derivation-name="{_PBKDF2}" manifest:key-size="32" manifest:iteration-count="1024" manifest:salt="{salt_value}"/>
  <manifest:start-key-generation manifest:start-key-generation-name="{_SHA256}" manifest:key-size="32"/>
 </manifest:encryption-data>
</manifest:file-entry>'''


def _package(
    path: Path,
    declarations: str,
    *,
    include_target: bool = True,
    section_payload: bytes = _CIPHERTEXT,
) -> Path:
    manifest = (
        f'<manifest:manifest xmlns:manifest="{_NS}" manifest:version="1.2">'
        f"{declarations}</manifest:manifest>"
    ).encode()
    content_hpf = (
        b'<opf:package xmlns:opf="http://www.idpf.org/2007/opf">'
        b'<opf:metadata/><opf:manifest><opf:item id="sec0" href="section0.xml" '
        b'media-type="application/xml"/></opf:manifest><opf:spine><opf:itemref '
        b'idref="sec0"/></opf:spine></opf:package>'
    )
    entries = [
        ("mimetype", b"application/hwp+zip"),
        ("META-INF/manifest.xml", manifest),
        ("Contents/content.hpf", content_hpf),
    ]
    if include_target:
        entries.append(("Contents/section0.xml", section_payload))
    else:
        entries.append(("Contents/section1.xml", section_payload))
    with zipfile.ZipFile(path, "w") as archive:
        for index, (name, payload) in enumerate(entries):
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED if index in {0, 3} else zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return path


def _valid_declaration() -> str:
    return _entry("Contents/section0.xml", _PLAIN)


def _zip_part(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


def _set_zip_flags(path: Path, name: str, *, local: int, central: int) -> None:
    with zipfile.ZipFile(path) as archive:
        local_offset = archive.getinfo(name).header_offset
    raw = bytearray(path.read_bytes())
    central_offset = raw.index(b"PK\x01\x02")
    while bytes(raw[central_offset + 46 : central_offset + 46 + len(name)]) != name.encode():
        central_offset = raw.index(b"PK\x01\x02", central_offset + 4)
    _ = struct.pack_into("<H", raw, local_offset + 6, local)
    _ = struct.pack_into("<H", raw, central_offset + 8, central)
    _ = path.write_bytes(raw)


@pytest.mark.parametrize(("local", "central"), [(1, 0), (0, 1)])
def test_encrypted_hwpx_preflight_rejects_local_central_flag_disagreement(
    tmp_path: Path, local: int, central: int
) -> None:
    source = _package(tmp_path / "flags.hwpx", _valid_declaration())
    _set_zip_flags(source, "Contents/section0.xml", local=local, central=central)
    before = source.read_bytes()

    with pytest.raises(DocumentError) as caught:
        _ = HwpxAdapter().inspect(source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert caught.value.details["reason"] == "zip_integrity"
    assert "flags disagree" in caught.value.message
    assert source.read_bytes() == before


@pytest.mark.parametrize("fault", ["compression", "filename"])
def test_encrypted_hwpx_rejects_local_central_header_metadata_disagreement(
    tmp_path: Path, fault: str
) -> None:
    source = _package(tmp_path / "metadata.hwpx", _valid_declaration())
    name = "Contents/section0.xml"
    with zipfile.ZipFile(source) as archive:
        offset = archive.getinfo(name).header_offset
    raw = bytearray(source.read_bytes())
    if fault == "compression":
        struct.pack_into("<H", raw, offset + 8, zipfile.ZIP_DEFLATED)
    else:
        name_offset = offset + 30
        raw[name_offset : name_offset + len(name)] = b"Contents/section9.xml"
    source.write_bytes(raw)
    before = source.read_bytes()

    with pytest.raises(DocumentError) as caught:
        _ = HwpxAdapter().inspect(source)

    assert caught.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert caught.value.details["reason"] == "zip_integrity"
    assert "local and central directory" in caught.value.message
    assert source.read_bytes() == before


def test_manifest_without_encryption_does_not_require_password(tmp_path: Path) -> None:
    source = _package(tmp_path / "plain.hwpx", "", section_payload=_PLAIN)
    info = HwpxAdapter().inspect(source)

    assert info["encrypted"] is False
    assert info["password_required"] is False
    assert info["credential_state"] == "not_required"


def test_nested_encryption_declaration_stays_opaque_and_blocks_content(
    tmp_path: Path,
) -> None:
    nested = _valid_declaration().replace(
        "<manifest:encryption-data ",
        "<manifest:wrapper><manifest:encryption-data ",
    ).replace("</manifest:encryption-data>", "</manifest:encryption-data></manifest:wrapper>")
    source = _package(tmp_path / "nested.hwpx", nested)
    output = tmp_path / "output.hwpx"
    before = source.read_bytes()

    info = HwpxAdapter().inspect(source)

    assert info["encrypted"] is True
    assert info["encryption_state"] == "unsupported_encryption_state"
    assert info["paragraphs"] == []
    assert info["encrypted_parts"][0]["part"] == "Contents/section0.xml"
    with pytest.raises(DocumentError) as caught:
        _ = HwpxAdapter().patch_paragraph_text(
            source,
            output,
            ParagraphLocator("Contents/section0.xml", "secret"),
            "replacement",
        )
    assert caught.value.details["reason"] == "unsupported_encryption_state"
    assert source.read_bytes() == before
    assert not output.exists()


def test_orphan_encryption_declaration_fails_closed_without_exposing_content(
    tmp_path: Path,
) -> None:
    valid = _valid_declaration()
    start = valid.index("<manifest:encryption-data")
    end = valid.index("</manifest:encryption-data>") + len(
        "</manifest:encryption-data>"
    )
    source = _package(
        tmp_path / "orphan-encryption.hwpx",
        valid[start:end],
        section_payload=_PLAIN,
    )
    before = source.read_bytes()
    output = tmp_path / "output.hwpx"

    info = HwpxAdapter().inspect(source)

    assert info["encrypted"] is True
    assert info["encryption_state"] == "unsupported_encryption_state"
    assert info["encryption_declaration_state"] == "malformed"
    assert "orphan_encryption_declaration" in info["encryption_issues"]
    assert info["paragraphs"] == []
    assert info["encrypted_parts"] == []
    with pytest.raises(DocumentError) as caught:
        _ = HwpxAdapter().patch_paragraph_text(
            source,
            output,
            ParagraphLocator("Contents/section0.xml", "secret"),
            "replacement",
        )
    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert caught.value.details["reason"] == "unsupported_encryption_state"
    assert source.read_bytes() == before
    assert not output.exists()


def test_namespace_valid_declared_encryption_is_metadata_only_inventory(tmp_path: Path) -> None:
    source = _package(tmp_path / "protected.hwpx", _valid_declaration())
    info = HwpxAdapter().inspect(source)

    assert info["encrypted"] is True
    assert info["password_required"] is True
    assert info["credential_state"] == "required_not_supplied"
    assert info["encryption_state"] == "unsupported_encryption_state"
    assert info["encryption_declaration_state"] == "valid"
    assert info["paragraphs"] == []
    part = info["encrypted_parts"][0]
    assert part["part"] == "Contents/section0.xml"
    assert part["algorithm"] == _AES256
    assert part["key_derivation"] == _PBKDF2
    assert part["iteration_count"] == 1024
    encrypted_bytes = _zip_part(source, "Contents/section0.xml")
    assert encrypted_bytes != _PLAIN and b"classified" not in encrypted_bytes
    assert part["source_sha256"] == hashlib.sha256(encrypted_bytes).hexdigest()
    assert info["encryption_manifest_sha256"] == hashlib.sha256(
        _zip_part(source, "META-INF/manifest.xml")
    ).hexdigest()


@pytest.mark.parametrize(
    ("declarations", "include_target", "issue"),
    [
        (_valid_declaration().replace("Contents/section0.xml", "Contents/missing.xml"), False, "missing_target"),
        (_valid_declaration() + _valid_declaration(), True, "duplicate_target"),
        (_valid_declaration().replace("Contents/section0.xml", "https://example.invalid/section.xml"), True, "external_target"),
        (_valid_declaration().replace(_AES256, "http://www.w3.org/2001/04/xmlenc#tripledes-cbc"), True, "unsupported_algorithm"),
        (_valid_declaration().replace('iteration-count="1024"', 'iteration-count="1"'), True, "weak_iteration_count"),
        (_valid_declaration().replace(_b64(_SALT), "not-base64!"), True, "malformed_salt"),
    ],
)
def test_spoofed_or_unsupported_declarations_are_inventoried_fail_closed(
    tmp_path: Path,
    declarations: str,
    include_target: bool,
    issue: str,
) -> None:
    source = _package(tmp_path / "spoofed.hwpx", declarations, include_target=include_target)
    info = HwpxAdapter().inspect(source)
    assert info["encrypted"] is True
    assert info["encryption_state"] == "unsupported_encryption_state"
    assert info["encryption_declaration_state"] == "malformed"
    assert issue in info["encryption_issues"]


@pytest.mark.parametrize("operation", ["patch", "derive", "decrypt"])
def test_content_operations_refuse_without_output_or_source_change(
    tmp_path: Path,
    operation: str,
) -> None:
    source = _package(tmp_path / "protected.hwpx", _valid_declaration())
    output = tmp_path / "output.hwpx"
    before = source.read_bytes()
    adapter = HwpxAdapter()

    with pytest.raises(DocumentError) as caught:
        if operation == "patch":
            _ = adapter.patch_paragraph_text(
                source,
                output,
                ParagraphLocator("Contents/section0.xml", "secret"),
                "replacement",
            )
        elif operation == "derive":
            _ = adapter.derive_template(
                source,
                output,
                {"field": "replacement"},
                expected_source_sha256=hashlib.sha256(before).hexdigest(),
            )
        else:
            adapter.decrypt(source, output, password="fixture-password")

    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert caught.value.details["reason"] == "unsupported_encryption_state"
    assert source.read_bytes() == before
    assert not output.exists()


def test_service_inventories_encryption_before_generic_xml_scanning(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "encrypted.hwpx", _valid_declaration())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    artifact = {"uri": str(source), "content_hash": digest}
    service = DocumentService(tmp_path)

    inspected = service.inspect_document(artifact)
    raw_structure = inspected["structure"]
    assert isinstance(raw_structure, dict)
    structure = cast("dict[str, object]", raw_structure)
    raw_inventory = structure["inventory"]
    assert isinstance(raw_inventory, dict)
    inventory = cast("dict[str, object]", raw_inventory)
    assert inventory["encrypted"] is True
    assert inventory["encryption_state"] == "unsupported_encryption_state"
    raw_risks = inspected["risks"]
    assert isinstance(raw_risks, dict)
    risks = cast("dict[str, object]", raw_risks)
    assert risks["coverage"] == (
        "format-specific encrypted package metadata only"
    )

    with pytest.raises(DocumentError) as caught:
        _ = service.extract_document(artifact)
    assert caught.value.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
    assert caught.value.details["reason"] == "unsupported_encryption_state"
