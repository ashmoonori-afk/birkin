"""Bounded metadata-first scanning for Office ZIP packages."""

from __future__ import annotations

import hashlib
import io
import re
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from . import package_types as types
from .errors import DocumentError, DocumentErrorCode
from .limits import PackageLimits as BasePackageLimits
from .package_relationships import RelationshipPartError, external_relationships
from .package_types import DEFAULT_LIMITS, PackageLimits
from .package_xml import XMLPackageBudget, validate_xml
from .package_zip import ZipLocalHeaderError, validate_local_headers

_CHUNK_BYTES, _XML_SUFFIXES = 64 * 1024, (".xml", ".rels")
_ZIP_PREFIXES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
def _error(code: DocumentErrorCode, message: str, reason: str | None = None) -> DocumentError:
    return DocumentError(code, "import", message, details={} if reason is None else {"reason": reason})

def package_invalid(message: str, *, reason: str | None = None) -> DocumentError:
    return _error(DocumentErrorCode.PACKAGE_INVALID, message, reason)

def _resource(message: str, reason: str) -> DocumentError:
    return _error(DocumentErrorCode.LIMIT_EXCEEDED, message, reason)

def _capability(message: str, reason: str) -> DocumentError:
    return _error(DocumentErrorCode.CAPABILITY_UNAVAILABLE, message, reason)

def _normalize(limits: BasePackageLimits) -> PackageLimits:
    return limits if isinstance(limits, PackageLimits) else PackageLimits(limits.max_entries, limits.max_uncompressed_bytes, limits.max_entry_ratio)

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _is_special(info: zipfile.ZipInfo) -> bool:
    if info.create_system != 3:
        return False
    file_type = stat.S_IFMT(info.external_attr >> 16)
    return file_type not in {0, stat.S_IFREG, stat.S_IFDIR}

def _normalized_name(name: str) -> str:
    name = unicodedata.normalize("NFC", name.replace("\\", "/"))
    return "/".join(part for part in name.split("/") if part not in {"", "."})

def _validate_name(original: str, seen: set[str], *, is_directory: bool) -> str:
    name = unicodedata.normalize("NFC", original.replace("\\", "/"))
    normalized = _normalized_name(original)
    canonical = f"{normalized}/" if is_directory else normalized
    if normalized in seen:
        raise package_invalid(f"duplicate normalized package path: {normalized}")
    seen.add(normalized)
    unsafe = not name or "\x00" in name or name.startswith("/")
    unsafe |= re.match(r"^[A-Za-z]:/", name) is not None
    unsafe |= ".." in PurePosixPath(name).parts or original != name or name != canonical
    if unsafe:
        raise package_invalid(f"unsafe or noncanonical package path: {original}")
    return name

def _media_type(data: bytes) -> str | None:
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"),
        (b"BM", "image/bmp"), (b"II*\x00", "image/tiff"), (b"MM\x00*", "image/tiff"),
    )
    for signature, media_type in signatures:
        if data.startswith(signature):
            return media_type
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None

def _validate_local_metadata(
    archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]
) -> None:
    try:
        validate_local_headers(archive, infos)
    except ZipLocalHeaderError as exc:
        raise package_invalid(str(exc), reason="zip_integrity") from exc


def _validate_metadata(
    infos: list[zipfile.ZipInfo],
    limits: PackageLimits,
    budget: list[int],
    legacy: bool,
    xml_budget: XMLPackageBudget,
) -> list[str]:
    if len(infos) > limits.max_entries:
        raise _resource("too many package entries", "package_entries")
    seen: set[str] = set()
    names: list[str] = []
    archive_total = 0
    archive_xml_total = 0
    for info in infos:
        name = _validate_name(info.filename, seen, is_directory=info.is_dir())
        names.append(name)
        if _is_special(info):
            raise package_invalid(f"special package entry is forbidden: {name}")
        if info.flag_bits & 0x1:
            raise package_invalid(f"encrypted package entry is forbidden: {name}")
        ratio = info.file_size / max(info.compress_size, 1) if info.file_size else 0
        if ratio > limits.max_entry_ratio:
            raise _resource(f"package entry compression ratio exceeds limit: {name}", "entry_ratio")
        if name.lower().endswith(_XML_SUFFIXES) and info.file_size > limits.max_xml_bytes:
            raise _resource(f"XML part exceeds byte limit: {name}", "xml_bytes")
        if name.lower().endswith(_XML_SUFFIXES):
            archive_xml_total += info.file_size
        if "/media/" in f"/{name.lower()}" and info.file_size > limits.max_media_bytes:
            raise _resource(f"media part exceeds byte limit: {name}", "media_bytes")
        archive_total += info.file_size
    if budget[0] + archive_total > limits.max_uncompressed_bytes:
        if legacy:
            raise package_invalid("inflated package exceeds limit")
        raise _resource("inflated package exceeds cumulative limit", "package_uncompressed_bytes")
    budget[0] += archive_total
    if (
        xml_budget.bytes + archive_xml_total
        > limits.max_total_xml_bytes
    ):
        raise _resource(
            "package XML byte limit exceeded",
            "package_xml_bytes",
        )
    xml_budget.bytes += archive_xml_total
    return names

def _read_verified(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    data = bytearray()
    try:
        with archive.open(info) as source:
            while chunk := source.read(_CHUNK_BYTES):
                data.extend(chunk)
                if len(data) > info.file_size:
                    raise package_invalid("ZIP entry exceeded declared size", reason="zip_integrity")
    except (OSError, EOFError, zipfile.BadZipFile, RuntimeError) as exc:
        raise package_invalid(f"ZIP entry integrity failure: {info.filename}", reason="zip_integrity") from exc
    if len(data) != info.file_size:
        raise package_invalid("ZIP entry size mismatch", reason="zip_integrity")
    return bytes(data)

def _external_relationships(name: str, data: bytes) -> list[types.ExternalRelationship]:
    if not name.lower().endswith(".rels"):
        return []
    try:
        return external_relationships(name, data)
    except RelationshipPartError as exc:
        raise package_invalid(f"malformed relationship XML: {name}") from exc

def _active_content(name: str) -> types.ActiveContent | None:
    lowered = name.lower()
    if lowered.endswith("vbaproject.bin"):
        return {"part_uri": name, "kind": "macro"}
    if "/activex/" in f"/{lowered}":
        return {"part_uri": name, "kind": "active_x"}
    if "/embeddings/" in f"/{lowered}":
        return {"part_uri": name, "kind": "embedded_object"}
    return None

def _scan_archive(
    archive: zipfile.ZipFile,
    limits: PackageLimits,
    budget: list[int],
    depth: int,
    legacy: bool,
    xml_budget: XMLPackageBudget,
) -> tuple[list[zipfile.ZipInfo], list[str], list[bytes]]:
    infos = archive.infolist()
    _validate_local_metadata(archive, infos)
    names = _validate_metadata(
        infos,
        limits,
        budget,
        legacy,
        xml_budget,
    )
    data = [_read_verified(archive, info) for info in infos]
    for name, content in zip(names, data, strict=True):
        if name.lower().endswith(_XML_SUFFIXES):
            validate_xml(name, content, limits, xml_budget)
        if "/media/" in f"/{name.lower()}":
            constrained = any(value is not None for value in (limits.max_media_width, limits.max_media_height, limits.max_media_pixels, limits.max_media_frames))
            if constrained:
                raise _capability("image dimension, pixel, and frame checks are unavailable at package preflight", "media_metadata")
            allowed = limits.allowed_media_types
            if allowed is not None and _media_type(content) not in allowed:
                raise package_invalid(f"media type is not allowed: {name}", reason="media_type")
        if "/embeddings/" in f"/{name.lower()}" and content.startswith(_ZIP_PREFIXES):
            if depth >= limits.max_package_depth:
                raise _error(DocumentErrorCode.POLICY_DENIED, "embedded package depth exceeds policy", "package_depth")
            with zipfile.ZipFile(io.BytesIO(content)) as nested:
                _ = _scan_archive(
                    nested,
                    limits,
                    budget,
                    depth + 1,
                    legacy,
                    xml_budget,
                )
    return infos, names, data

def preflight_package(path: Path, limits: BasePackageLimits = DEFAULT_LIMITS) -> types.PackageManifest:
    try:
        package_path = Path(path)
        legacy = not isinstance(limits, PackageLimits)
        effective = _normalize(limits)
        with zipfile.ZipFile(package_path) as archive:
            infos, names, payloads = _scan_archive(
                archive,
                effective,
                [0],
                0,
                legacy,
                XMLPackageBudget(),
            )
            parts: dict[str, types.PartManifest] = {}
            external: list[types.ExternalRelationship] = []
            active: list[types.ActiveContent] = []
            for index, (info, name, data) in enumerate(zip(infos, names, payloads, strict=True)):
                external.extend(_external_relationships(name, data))
                finding = _active_content(name)
                if finding is not None:
                    active.append(finding)
                parts[name] = {"index": index, "original_sha256": hashlib.sha256(data).hexdigest(), "bytes": data, "compress_type": info.compress_type, "date_time": info.date_time, "external_attr": info.external_attr, "create_system": info.create_system, "header_offset": info.header_offset}
        return {"parts": parts, "source_sha256": sha256_file(package_path), "external_relationships": external, "active_content": active}
    except DocumentError:
        raise
    except (OSError, EOFError, zipfile.BadZipFile, RuntimeError) as exc:
        raise package_invalid(str(exc), reason="zip_integrity") from exc
