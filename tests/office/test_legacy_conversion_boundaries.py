from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from birkin.office.legacy_conversion import convert_legacy, probe_legacy_converter
from birkin.office.legacy_preflight import preflight_legacy
from birkin.office.legacy_types import (
    LegacyConversionRequest,
    LegacyEnginePin,
    LegacyRefusal,
    LegacySandboxPolicy,
)

_CFB_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
_FREE = 0xFFFFFFFF
_END = 0xFFFFFFFE
_FAT = 0xFFFFFFFD


def _directory_entry(name: str, entry_type: int = 2) -> bytes:
    encoded = (name + "\0").encode("utf-16le")
    entry = bytearray(128)
    entry[: len(encoded)] = encoded
    struct.pack_into("<H", entry, 64, len(encoded))
    entry[66] = entry_type
    struct.pack_into("<III", entry, 68, _FREE, _FREE, _FREE)
    struct.pack_into("<I", entry, 116, _END)
    return bytes(entry)


def _cfb(*names: str) -> bytes:
    entries = [_directory_entry("Root Entry", 5), *(_directory_entry(name) for name in names)]
    directory_count = (len(entries) + 3) // 4
    directory_sectors: list[bytes] = []
    for index in range(directory_count):
        block = b"".join(entries[index * 4 : (index + 1) * 4])
        directory_sectors.append(block.ljust(512, b"\0"))
    fat_id = directory_count
    header = bytearray(512)
    header[:8] = _CFB_MAGIC
    struct.pack_into("<HHHH", header, 24, 0x003E, 3, 0xFFFE, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, 1, 0, 0, 4096, _END, 0, _END, 0)
    struct.pack_into("<109I", header, 76, fat_id, *([_FREE] * 108))
    fat = [_FREE] * 128
    for index in range(directory_count):
        fat[index] = index + 1 if index + 1 < directory_count else _END
    fat[fat_id] = _FAT
    return bytes(header) + b"".join(directory_sectors) + struct.pack("<128I", *fat)


@pytest.mark.parametrize(
    ("extension", "identity", "expected"),
    [("doc", "WordDocument", "doc"), ("xls", "Workbook", "xls"), ("ppt", "PowerPoint Document", "ppt")],
)
def test_real_cfb_identity_requires_matching_extension(
    tmp_path: Path, extension: str, identity: str, expected: str
) -> None:
    source = tmp_path / f"minimal.{extension}"
    _ = source.write_bytes(_cfb(identity))

    result = preflight_legacy(source)

    assert result.format == expected
    assert result.container == "cfb"
    assert result.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.native_edit_supported is False
    assert result.native_create_supported is False
    assert result.allowed_operations == ("read_extract", "convert")


def test_cfb_inventory_reports_only_provable_directory_markers(tmp_path: Path) -> None:
    source = tmp_path / "risky.doc"
    _ = source.write_bytes(
        _cfb("WordDocument", "EncryptionInfo", "Macros", "ObjectPool")
    )

    inventory = set(preflight_legacy(source).inventory)

    assert {"encrypted", "macro_content", "embedded_ole"} <= inventory


@pytest.mark.parametrize(
    ("name", "payload", "code", "identified"),
    [
        ("renamed.doc", b"{\\rtf1\\ansi renamed}", "extension_magic_mismatch", "rtf"),
        ("renamed.rtf", _cfb("WordDocument"), "extension_magic_mismatch", "doc"),
        ("hybrid.doc", _cfb("WordDocument", "Workbook"), "hybrid_identity", None),
        ("fake.xls", b"not an ole spreadsheet", "unsupported_magic", None),
    ],
)
def test_renamed_hybrid_and_fake_inputs_are_hash_bound_refusals(
    tmp_path: Path, name: str, payload: bytes, code: str, identified: str | None
) -> None:
    source = tmp_path / name
    _ = source.write_bytes(payload)

    with pytest.raises(LegacyRefusal) as caught:
        _ = preflight_legacy(source)

    receipt = caught.value.receipt
    assert receipt.reason_code == code
    assert receipt.source_format == identified
    assert receipt.source_sha256 == hashlib.sha256(payload).hexdigest()
    assert receipt.output is None


def test_rtf_is_not_cfb_and_hostile_controls_and_encoding_are_inventoried(tmp_path: Path) -> None:
    source = tmp_path / "hostile.rtf"
    payload = b"{\\rtf1\\ansi\\ansicpg932{\\object{\\*\\objdata 0102}}" + (
        b"{\\protect\\field{\\*\\fldinst DDEAUTO c:\\\\host}}{\\htmltag <script>x</script>}}"
    )
    _ = source.write_bytes(payload)

    result = preflight_legacy(source)

    assert result.container == "rtf"
    assert result.encoding == "windows-932"
    assert {
        "embedded_object",
        "embedded_object_data",
        "field",
        "field_instruction",
        "external_update",
        "html_content",
        "protected",
    } <= set(result.inventory)
    assert "objects" in result.prospective_loss_categories


def test_pin_and_sandbox_contract_cannot_claim_native_editing() -> None:
    with pytest.raises(ValueError, match="exact"):
        _ = LegacyEnginePin(
            "libreoffice", "latest", "MS Word 97", "Office Open XML Text"
        )
    policy = LegacySandboxPolicy()
    assert policy.network == "offline" and policy.max_jobs == 1 and policy.source_read_only
    assert policy.jailed_temporary_directory and policy.process_tree_cleanup == "kill_and_reap"
    assert not policy.macros_enabled and not policy.scripts_enabled
    assert not policy.ole_activation_enabled and not policy.external_updates_enabled


def test_unavailable_converter_receipt_leaves_source_output_and_temp_untouched(tmp_path: Path) -> None:
    source = tmp_path / "source.doc"
    output = tmp_path / "output.docx"
    _ = source.write_bytes(_cfb("WordDocument", "Macros"))
    before = source.read_bytes()
    request = LegacyConversionRequest(
        target_format="docx",
        engine=LegacyEnginePin(
            "libreoffice",
            "24.2.7.2",
            "MS Word 97",
            "Office Open XML Text",
        ),
    )

    receipt = convert_legacy(source, output, request)

    assert receipt.status == "converter_unavailable"
    assert receipt.reason_code in {"converter_unavailable", "isolated_runner_unavailable"}
    assert receipt.source_sha256 == hashlib.sha256(before).hexdigest()
    assert receipt.output is None and not output.exists()
    assert source.read_bytes() == before
    assert set(tmp_path.iterdir()) == {source}
    if probe_legacy_converter(request) is None:
        assert receipt.reason_code == "converter_unavailable"
