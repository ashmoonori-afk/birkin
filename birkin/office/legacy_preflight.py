"""Bounded identity and risk preflight for binary Office and RTF inputs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .legacy_types import (
    LegacyFormat,
    LegacyLimits,
    LegacyPreflight,
    LegacyReceipt,
    LegacyRefusal,
)

_CFB_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
_END = 0xFFFFFFFE
_FREE = 0xFFFFFFFF
_SPECIAL = 0xFFFFFFFC
_IDENTITIES: dict[str, LegacyFormat] = {
    "worddocument": "doc",
    "workbook": "xls",
    "book": "xls",
    "powerpoint document": "ppt",
}
_LOSS: dict[LegacyFormat, tuple[str, ...]] = {
    "doc": ("legacy_layout", "fonts", "fields", "macros", "embedded_ole", "revision_history"),
    "xls": ("legacy_formula_semantics", "formatting", "macros", "embedded_ole", "external_links"),
    "ppt": ("legacy_layout", "fonts", "animations", "macros", "embedded_ole", "media"),
    "rtf": ("layout", "fonts", "fields", "objects", "encoding", "unknown_destinations"),
}
_RTF_CONTROL = re.compile(rb"\\([A-Za-z]+)(-?\d+)? ?")
_RTF_RISKS: dict[bytes, str] = {
    b"object": "embedded_object",
    b"objdata": "embedded_object_data",
    b"field": "field",
    b"fldinst": "field_instruction",
    b"dde": "external_update",
    b"ddeauto": "external_update",
    b"link": "external_link",
    b"includetext": "external_update",
    b"includepicture": "external_update",
    b"htmltag": "html_content",
    b"script": "script_content",
    b"protect": "protected",
    b"formprot": "protected",
    b"annotprot": "protected",
    b"readprot": "protected",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _refuse(
    digest: str,
    reason_code: str,
    reason: str,
    *,
    source_format: str | None = None,
) -> LegacyRefusal:
    losses = next(
        (categories for format_name, categories in _LOSS.items() if format_name == source_format),
        ("unclassified_legacy_content",),
    )
    return LegacyRefusal(
        LegacyReceipt(
            status="refused",
            source_sha256=digest,
            source_format=source_format,
            target_format=None,
            prospective_loss_categories=losses,
            reason_code=reason_code,
            reason=reason,
            engine=None,
            policy=None,
        )
    )


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def _sector(data: bytes, sector_size: int, sector_id: int, limit: int) -> bytes:
    if sector_id < 0 or sector_id >= limit:
        raise ValueError("sector index is outside the file")
    start = 512 + sector_id * sector_size
    end = start + sector_size
    if end > len(data):
        raise ValueError("truncated CFB sector")
    return data[start:end]


def _cfb_directory_names(data: bytes, limits: LegacyLimits) -> tuple[str, ...]:
    if len(data) < 512 or data[:8] != _CFB_MAGIC:
        raise ValueError("missing CFB header")
    if data[28:30] != b"\xfe\xff":
        raise ValueError("unsupported CFB byte order")
    sector_shift = _u16(data, 30)
    if sector_shift not in (9, 12):
        raise ValueError("invalid CFB sector size")
    sector_size = 1 << sector_shift
    sector_count = (len(data) - 512) // sector_size
    if sector_count <= 0 or sector_count > limits.max_cfb_sectors:
        raise ValueError("CFB sector limit exceeded")
    fat_count = _u32(data, 44)
    first_directory = _u32(data, 48)
    if fat_count == 0 or fat_count > sector_count:
        raise ValueError("invalid CFB FAT count")
    difat = [_u32(data, offset) for offset in range(76, 512, 4)]
    if fat_count > 109:
        raise ValueError("extended CFB DIFAT is not accepted by this preflight")
    fat_ids = [value for value in difat if value != _FREE][:fat_count]
    if len(fat_ids) != fat_count:
        raise ValueError("truncated CFB FAT")
    fat: list[int] = []
    for sector_id in fat_ids:
        fat_sector = _sector(data, sector_size, sector_id, sector_count)
        fat.extend(_u32(fat_sector, offset) for offset in range(0, sector_size, 4))

    names: list[str] = []
    seen: set[int] = set()
    current = first_directory
    while current != _END:
        if current in seen or current >= len(fat) or len(seen) >= limits.max_cfb_sectors:
            raise ValueError("invalid CFB directory chain")
        seen.add(current)
        directory = _sector(data, sector_size, current, sector_count)
        for offset in range(0, sector_size, 128):
            entry = directory[offset : offset + 128]
            entry_type = entry[66]
            if entry_type not in (1, 2, 5):
                continue
            name_bytes = _u16(entry, 64)
            if name_bytes < 2 or name_bytes > 64 or name_bytes % 2:
                raise ValueError("invalid CFB directory name")
            name = entry[: name_bytes - 2].decode("utf-16le", "strict")
            names.append(name)
            if len(names) > limits.max_cfb_directory_entries:
                raise ValueError("CFB directory entry limit exceeded")
        current = fat[current]
        if current >= _SPECIAL and current != _END:
            raise ValueError("invalid CFB directory terminator")
    return tuple(names)


def _cfb_identity(data: bytes, limits: LegacyLimits) -> tuple[LegacyFormat, tuple[str, ...]]:
    names = _cfb_directory_names(data, limits)
    lowered = {name.casefold() for name in names}
    formats: set[LegacyFormat] = {_IDENTITIES[name] for name in lowered if name in _IDENTITIES}
    if len(formats) > 1:
        raise RuntimeError("hybrid CFB contains multiple Office identities")
    if not formats:
        raise LookupError("CFB has no DOC, XLS, or PPT identity stream")
    format_name = formats.pop()
    inventory: set[str] = {"cfb_container", f"identity:{format_name}"}
    for name in lowered:
        if any(marker in name for marker in ("encryptedpackage", "encryptioninfo", "drmcontent", "encryptedsummary")):
            inventory.add("encrypted")
        if any(marker in name for marker in ("vba", "macros", "_vba_project")):
            inventory.add("macro_content")
        if any(marker in name for marker in ("objectpool", "ole10native", "embedding")):
            inventory.add("embedded_ole")
    return format_name, tuple(sorted(inventory))


def _rtf_inventory(data: bytes, limits: LegacyLimits) -> tuple[tuple[str, ...], str]:
    controls = list(_RTF_CONTROL.finditer(data))
    if len(controls) > limits.max_rtf_controls:
        raise OverflowError("RTF control limit exceeded")
    names = {match.group(1).lower() for match in controls}
    inventory = {"rtf_control_stream"}
    inventory.update(risk for control, risk in _RTF_RISKS.items() if control in names)
    lowered = data.lower()
    if b"fldinst" in names and any(
        keyword in lowered
        for keyword in (b"ddeauto", b"includetext", b"includepicture", b" link ")
    ):
        inventory.add("external_update")
    codepage = next((match.group(2) for match in controls if match.group(1).lower() == b"ansicpg"), None)
    if codepage:
        encoding = f"windows-{codepage.decode('ascii').lstrip('+')}"
    elif b"mac" in names:
        encoding = "mac-roman"
    elif b"pc" in names or b"pca" in names:
        encoding = "dos-codepage-unspecified"
    else:
        encoding = "windows-1252-assumed"
    return tuple(sorted(inventory)), encoding


def preflight_legacy(path: Path, limits: LegacyLimits | None = None) -> LegacyPreflight:
    """Identify a real legacy container without executing or interpreting its content."""
    effective_limits = limits or LegacyLimits()
    source = Path(path)
    digest = _sha256(source)
    size = source.stat().st_size
    if size > effective_limits.max_input_bytes:
        raise _refuse(digest, "input_limit", "legacy input exceeds the byte limit")
    data = source.read_bytes()
    suffix = source.suffix.lower().removeprefix(".")
    if data.startswith(_CFB_MAGIC):
        try:
            format_name, inventory = _cfb_identity(data, effective_limits)
        except RuntimeError as error:
            raise _refuse(digest, "hybrid_identity", str(error)) from error
        except (LookupError, ValueError) as error:
            raise _refuse(digest, "invalid_cfb_identity", str(error)) from error
        container = "cfb"
        encoding = None
    elif data.startswith(b"{\\rtf"):
        format_name = "rtf"
        try:
            inventory, encoding = _rtf_inventory(data, effective_limits)
        except OverflowError as error:
            raise _refuse(digest, "input_limit", str(error), source_format="rtf") from error
        container = "rtf"
    else:
        raise _refuse(digest, "unsupported_magic", "input is neither CFB/OLE nor RTF")
    if suffix != format_name:
        raise _refuse(
            digest,
            "extension_magic_mismatch",
            f".{suffix or '<none>'} extension does not match {format_name} content",
            source_format=format_name,
        )
    return LegacyPreflight(
        status="accepted",
        format=format_name,
        source=source,
        source_sha256=digest,
        size_bytes=size,
        container=container,
        inventory=inventory,
        encoding=encoding,
        prospective_loss_categories=_LOSS[format_name],
    )
