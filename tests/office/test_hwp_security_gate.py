from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import cast

import pytest

from birkin.office.hwp_security_gate import inspect_hwp_security, require_hwp_capability
from birkin.office.hwp_types import HwpRefusal

_CFB_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
_FREE = 0xFFFFFFFF
_END = 0xFFFFFFFE
_FAT = 0xFFFFFFFD


def _entry(
    name: str,
    entry_type: int,
    *,
    start: int = _END,
    size: int = 0,
    left: int = _FREE,
    right: int = _FREE,
    child: int = _FREE,
) -> bytes:
    encoded = (name + "\0").encode("utf-16le")
    item = bytearray(128)
    item[: len(encoded)] = encoded
    struct.pack_into("<H", item, 64, len(encoded))
    item[66] = entry_type
    item[67] = 1
    struct.pack_into("<III", item, 68, left, right, child)
    struct.pack_into("<I", item, 116, start)
    struct.pack_into("<Q", item, 120, size)
    return bytes(item)


def _hwp(
    *, flags: int = 0, view_text: bool = False, signature: bytes | None = None
) -> bytes:
    file_header = bytearray(256)
    file_header[:32] = (signature or b"HWP Document File").ljust(32, b"\0")
    file_header[32:36] = bytes((1, 0, 0, 5))
    struct.pack_into("<I", file_header, 36, flags)
    mini_stream = bytes(file_header) + b"D" + (b"\0" * 63) + b"S"
    mini_stream = mini_stream.ljust(512, b"\0")

    storage = "ViewText" if view_text else "BodyText"
    entries = [
        _entry("Root Entry", 5, start=2, size=len(mini_stream), child=3),
        _entry("FileHeader", 2, start=0, size=256),
        _entry("DocInfo", 2, start=4, size=1),
        _entry(storage, 1, left=2, right=1, child=4),
        _entry("Section0", 2, start=5, size=1),
    ]
    directories: list[bytes] = []
    for offset in range(0, len(entries), 4):
        directories.append(b"".join(entries[offset : offset + 4]).ljust(512, b"\0"))

    mini_fat_id = len(directories) + 1
    fat_id = mini_fat_id + 1
    header = bytearray(512)
    header[:8] = _CFB_MAGIC
    struct.pack_into("<HHHH", header, 24, 0x003E, 3, 0xFFFE, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into(
        "<IIIIIIIII", header, 40, 0, 1, 0, 0, 4096, mini_fat_id, 1, _END, 0
    )
    struct.pack_into("<109I", header, 76, fat_id, *([_FREE] * 108))

    fat = [_FREE] * 128
    for index in range(len(directories)):
        fat[index] = index + 1 if index + 1 < len(directories) else _END
    fat[len(directories)] = _END  # root mini stream
    fat[mini_fat_id] = _END
    fat[fat_id] = _FAT
    mini_fat = [_FREE] * 128
    mini_fat[0:6] = [1, 2, 3, _END, _END, _END]
    return (
        bytes(header)
        + b"".join(directories)
        + mini_stream
        + struct.pack("<128I", *mini_fat)
        + struct.pack("<128I", *fat)
    )


def _write(path: Path, payload: bytes) -> Path:
    _ = path.write_bytes(payload)
    return path


def _capabilities(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return cast("dict[str, dict[str, object]]", report["capabilities"])


def test_real_hwp_fileheader_flags_are_reported_without_reading_body(
    tmp_path: Path,
) -> None:
    flags = (1 << 0) | (1 << 3) | (1 << 7) | (1 << 9)
    source = _write(tmp_path / "markers.hwp", _hwp(flags=flags))

    report = inspect_hwp_security(source)

    assert report["format"] == "hwp" and report["container"] == "cfb"
    assert report["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    evidence = cast(dict[str, object], report["flag_evidence"])
    assert evidence["raw_flags"] == flags
    assert evidence["compressed"] is True
    assert evidence["script"] is True
    assert evidence["digital_signature"] is True
    assert evidence["signature_reserve"] is True
    assert report["encrypted"] is False and report["distribution_document"] is False
    assert {"FileHeader", "DocInfo", "BodyText", "Section0"} <= set(
        cast(list[str], report["directory_inventory"])
    )
    assert _capabilities(report)["inspect"]["state"] == "available"
    assert (
        _capabilities(report)["read"]["reason_code"]
        == "hwp_approved_engine_unavailable"
    )


@pytest.mark.parametrize(
    ("flags", "view_text", "states", "reason"),
    [
        (
            1 << 2,
            True,
            {"distribution_document": True},
            "hwp_distribution_document_refused",
        ),
        (
            1 << 1,
            False,
            {"encrypted": True, "password_protected": True},
            "hwp_password_decryptor_unavailable",
        ),
        (1 << 4, False, {"drm_protected": True}, "hwp_drm_document_refused"),
        (
            1 << 8,
            False,
            {"encrypted": True, "certificate_encrypted": True},
            "hwp_certificate_decryptor_unavailable",
        ),
        (1 << 10, False, {"drm_protected": True}, "hwp_drm_document_refused"),
    ],
)
def test_protected_hwp_states_refuse_every_content_operation(
    tmp_path: Path,
    flags: int,
    view_text: bool,
    states: dict[str, bool],
    reason: str,
) -> None:
    source = _write(tmp_path / "protected.hwp", _hwp(flags=flags, view_text=view_text))
    before = source.read_bytes()

    report = inspect_hwp_security(source)

    for name, expected in states.items():
        assert report[name] is expected
    capabilities = _capabilities(report)
    assert capabilities["inspect"]["state"] == "available"
    for operation in ("read", "extract", "convert", "edit", "render"):
        assert capabilities[operation]["state"] == "refused"
        assert capabilities[operation]["reason_code"] == reason
        tool = cast(dict[str, object], capabilities[operation]["required_tool"])
        assert tool["approved"] is False
        assert tool["status"] == "unavailable"
        assert (
            tool["provenance_requirement"] == "exact-name+version+artifact-hash+license"
        )
        with pytest.raises(HwpRefusal) as caught:
            _ = require_hwp_capability(source, operation)
        assert caught.value.receipt["source_sha256"] == report["source_sha256"]
        assert caught.value.receipt["output"] is None
    assert capabilities["create"]["state"] == "unavailable"
    assert source.read_bytes() == before
    assert set(tmp_path.iterdir()) == {source}


def test_distribution_layout_must_use_viewtext_and_is_never_plain_body(
    tmp_path: Path,
) -> None:
    mismatched = _write(tmp_path / "bad-distribution.hwp", _hwp(flags=1 << 2))
    with pytest.raises(HwpRefusal) as caught:
        _ = inspect_hwp_security(mismatched)
    assert caught.value.receipt["reason_code"] == "hwp_distribution_layout_invalid"

    plain_view = _write(tmp_path / "bad-plain.hwp", _hwp(view_text=True))
    with pytest.raises(HwpRefusal) as plain:
        _ = inspect_hwp_security(plain_view)
    assert plain.value.receipt["reason_code"] == "hwp_body_layout_invalid"


@pytest.mark.parametrize(
    ("name", "payload", "reason"),
    [
        ("spoofed.hwpx", _hwp(), "hwp_extension_mismatch"),
        ("zip.hwp", b"PK\x03\x04not-an-hwp", "hwp_cfb_magic_invalid"),
        ("truncated.hwp", _CFB_MAGIC + b"\0" * 80, "hwp_cfb_invalid"),
        (
            "signature.hwp",
            _hwp(signature=b"Spoof Document File"),
            "hwp_fileheader_signature_invalid",
        ),
    ],
)
def test_spoofed_and_malformed_inputs_are_hash_bound_refusals(
    tmp_path: Path, name: str, payload: bytes, reason: str
) -> None:
    source = _write(tmp_path / name, payload)
    with pytest.raises(HwpRefusal) as caught:
        _ = inspect_hwp_security(source)
    assert caught.value.receipt == {
        "status": "refused",
        "operation": "inspect",
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "reason_code": reason,
        "reason": caught.value.receipt["reason"],
        "required_tool": None,
        "output": None,
    }
