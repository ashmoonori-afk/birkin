"""Bounded HWPX container scan when declared parts are opaque ciphertext."""

from __future__ import annotations

import hashlib
import re
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from birkin.office.safe_xml import ElementTree
from birkin.office.safe_xml import DefusedXmlException

from ..errors import DocumentError, DocumentErrorCode
from ..package_types import DEFAULT_LIMITS, PackageManifest, PartManifest
from ..package_zip import ZipLocalHeaderError, read_local_header, validate_local_headers
from .hwpx_encryption import declared_encryption_targets

_MANIFEST = "META-INF/manifest.xml"


def _invalid(message: str, reason: str = "hwpx_encrypted_container") -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PACKAGE_INVALID,
        "import",
        message,
        details={"reason": reason},
    )


def _limit(message: str, reason: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.LIMIT_EXCEEDED,
        "import",
        message,
        details={"reason": reason},
    )


def _name(info: zipfile.ZipInfo, seen: set[str]) -> str:
    original = info.filename
    name = unicodedata.normalize("NFC", original.replace("\\", "/"))
    normalized = "/".join(part for part in name.split("/") if part not in {"", "."})
    canonical = f"{normalized}/" if info.is_dir() else normalized
    if normalized in seen:
        raise _invalid(f"duplicate normalized package path: {normalized}")
    seen.add(normalized)
    special = info.create_system == 3 and stat.S_IFMT(info.external_attr >> 16) not in {
        0, stat.S_IFREG, stat.S_IFDIR,
    }
    unsafe = (
        not name
        or "\x00" in name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:/", name) is not None
        or ".." in PurePosixPath(name).parts
        or original != name
        or name != canonical
    )
    if unsafe or special:
        raise _invalid(f"unsafe package entry: {original}")
    if info.flag_bits & 1:
        raise _invalid(f"ZIP-level encrypted entry is unsupported: {name}")
    return name


def _validate_local_metadata(
    archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]
) -> None:
    try:
        validate_local_headers(archive, infos)
    except ZipLocalHeaderError as exc:
        raise _invalid(str(exc), "zip_integrity") from exc


def _raw_payload(source: Path, info: zipfile.ZipInfo) -> bytes:
    try:
        with source.open("rb") as stream:
            local = read_local_header(stream, info)
            _ = stream.seek(local.payload_offset)
            payload = stream.read(info.compress_size)
    except ZipLocalHeaderError as exc:
        raise _invalid(str(exc), "zip_integrity") from exc
    if len(payload) != info.compress_size:
        raise _invalid(f"truncated encrypted package entry: {info.filename}", "zip_integrity")
    return payload


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    try:
        data = archive.read(info)
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile) as exc:
        raise _invalid(f"ZIP entry integrity failure: {info.filename}", "zip_integrity") from exc
    if len(data) != info.file_size:
        raise _invalid(f"ZIP entry size mismatch: {info.filename}", "zip_integrity")
    return data


def _xml(data: bytes, name: str) -> None:
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", data, re.IGNORECASE):
        raise _invalid(f"DTD and entities are forbidden: {name}")
    try:
        root = ElementTree.fromstring(data, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise _invalid(f"malformed XML: {name}") from exc
    count = sum(1 for _ in root.iter())
    if count > DEFAULT_LIMITS.max_xml_nodes:
        raise _limit(f"XML node limit exceeded: {name}", "xml_nodes")


def _probe_manifest(source: Path) -> bytes | None:
    try:
        with zipfile.ZipFile(source) as archive:
            matches = [info for info in archive.infolist() if info.filename == _MANIFEST]
            if len(matches) != 1 or matches[0].file_size > DEFAULT_LIMITS.max_xml_bytes:
                return None
            return _read(archive, matches[0])
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, DocumentError):
        return None


def has_encryption_declaration(source: Path) -> bool:
    raw = _probe_manifest(source)
    if raw is None:
        return False
    try:
        root = ElementTree.fromstring(raw, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException):
        return False
    return any(element.tag.rsplit("}", 1)[-1] == "encryption-data" for element in root.iter())


def preflight_encrypted_hwpx(source: Path) -> PackageManifest:
    """Read metadata normally and ciphertext as opaque source evidence."""
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            _validate_local_metadata(archive, infos)
            if len(infos) > DEFAULT_LIMITS.max_entries:
                raise _limit("too many package entries", "package_entries")
            seen: set[str] = set()
            names = [_name(info, seen) for info in infos]
            by_name = dict(zip(names, infos, strict=True))
            manifest_info = by_name.get(_MANIFEST)
            if manifest_info is None:
                raise _invalid("encrypted HWPX declaration requires META-INF/manifest.xml")
            manifest_raw = _read(archive, manifest_info)
            _xml(manifest_raw, _MANIFEST)
            targets = set(declared_encryption_targets(manifest_raw))
            total = sum(max(info.file_size, info.compress_size) for info in infos)
            if total > DEFAULT_LIMITS.max_uncompressed_bytes:
                raise _limit("inflated package exceeds cumulative limit", "package_uncompressed_bytes")
            parts: dict[str, PartManifest] = {}
            for index, (name, info) in enumerate(zip(names, infos, strict=True)):
                ratio = info.file_size / max(info.compress_size, 1) if info.file_size else 0
                if ratio > DEFAULT_LIMITS.max_entry_ratio:
                    raise _limit(f"package entry compression ratio exceeds limit: {name}", "entry_ratio")
                if name in targets:
                    data = _raw_payload(source, info) if info.compress_type != zipfile.ZIP_STORED else _read(archive, info)
                else:
                    data = manifest_raw if name == _MANIFEST else _read(archive, info)
                    if name.lower().endswith((".xml", ".rels", ".hpf")):
                        if len(data) > DEFAULT_LIMITS.max_xml_bytes:
                            raise _limit(f"XML part exceeds byte limit: {name}", "xml_bytes")
                        # A malformed declaration makes all section bytes untrusted and
                        # inaccessible; identity remains name/manifest based only.
                        if not name.startswith("Contents/section"):
                            _xml(data, name)
                parts[name] = {
                    "index": index,
                    "original_sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": data,
                    "compress_type": info.compress_type,
                    "date_time": info.date_time,
                    "external_attr": info.external_attr,
                    "create_system": info.create_system,
                    "header_offset": info.header_offset,
                }
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return {
            "parts": parts,
            "source_sha256": digest,
            "external_relationships": [],
            "active_content": [],
        }
    except DocumentError:
        raise
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile) as exc:
        raise _invalid(str(exc), "zip_integrity") from exc
