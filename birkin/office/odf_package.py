"""Bounded ODT/ODS/ODP identity, manifest, and exact-clone boundary."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from defusedxml import ElementTree

from .errors import DocumentError, DocumentErrorCode
from .limits import PackageLimits as BasePackageLimits
from .odf_types import (
    OdfCloneReceipt,
    OdfFormat,
    OdfManifestEntry,
    OdfPreflight,
    OdfRole,
    OdfSecurityFinding,
    OdfSecurityKind,
)
from .package_scan import preflight_package, sha256_file
from .package_types import DEFAULT_LIMITS, PackageManifest, PartManifest

_MANIFEST = "META-INF/manifest.xml"
_NS = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
_MEDIA: dict[str, tuple[OdfFormat, str]] = {
    ".odt": ("odt", "application/vnd.oasis.opendocument.text"),
    ".ods": ("ods", "application/vnd.oasis.opendocument.spreadsheet"),
    ".odp": ("odp", "application/vnd.oasis.opendocument.presentation"),
}
_CORE = frozenset(("content.xml", "styles.xml", "meta.xml", "settings.xml"))


def _invalid(message: str, reason: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PACKAGE_INVALID, "import", message, details={"reason": reason}
    )


def _identity(path: Path, manifest: PackageManifest) -> tuple[OdfFormat, str]:
    expected = _MEDIA.get(path.suffix.lower())
    if expected is None:
        raise _invalid("ODF source extension must be .odt, .ods, or .odp", "odf_identity")
    parts = manifest["parts"]
    if "mimetype" not in parts or _MANIFEST not in parts:
        raise _invalid("ODF package requires mimetype and META-INF/manifest.xml", "odf_identity")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not infos or infos[0].filename != "mimetype":
            raise _invalid("ODF mimetype must be the first ZIP entry", "odf_mimetype_order")
        first = infos[0]
        if first.compress_type != zipfile.ZIP_STORED or first.header_offset != 0:
            raise _invalid("ODF mimetype must be first and uncompressed", "odf_mimetype_storage")
        with path.open("rb") as stream:
            header = stream.read(30)
            if len(header) != 30 or header[:4] != b"PK\x03\x04":
                raise _invalid("invalid ODF mimetype local header", "odf_mimetype_header")
            compression = int.from_bytes(header[8:10], "little")
            name_size = int.from_bytes(header[26:28], "little")
            extra_size = int.from_bytes(header[28:30], "little")
            name = stream.read(name_size)
        if compression != 0 or name != b"mimetype" or extra_size != 0:
            raise _invalid("ODF mimetype local header is not canonical", "odf_mimetype_header")
    payload = parts["mimetype"]
    if payload["bytes"] != expected[1].encode("ascii"):
        raise _invalid("ODF extension and mimetype disagree", "odf_identity")
    return expected


def _manifest_path(value: str) -> str:
    if value == "/":
        return value
    decoded = unquote(value)
    normalized = unicodedata.normalize("NFC", value)
    decoded_parts = PurePosixPath(decoded.replace("\\", "/")).parts
    unsafe = (
        not value
        or value != normalized
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or "?" in value
        or "#" in value
        or ".." in decoded_parts
        or decoded.startswith("/")
        or re.match(r"^[A-Za-z]:", decoded) is not None
    )
    canonical = "/".join(part for part in value.split("/") if part not in {"", "."})
    if value.endswith("/"):
        canonical += "/"
    if unsafe or value != canonical:
        raise _invalid(f"unsafe or noncanonical ODF manifest path: {value}", "odf_manifest_path")
    return value


def _role(path: str, media_type: str, encrypted: bool) -> OdfRole:
    lowered = f"/{path.lower()}"
    if path == "/":
        return "root"
    if encrypted:
        return "encrypted"
    if path.endswith("/"):
        return "directory"
    if path in _CORE:
        return "core"
    if "signature" in lowered and lowered.startswith("/meta-inf/"):
        return "signature"
    if re.search(r"/(?:basic|macros?)/", lowered):
        return "macro"
    if re.search(r"/(?:scripts?)/", lowered):
        return "script"
    if lowered.startswith("/object ") or "oleobject" in media_type.lower():
        return "embedded_object"
    if lowered.startswith("/pictures/") or media_type.startswith(("image/", "audio/", "video/")):
        return "media"
    return "unknown"


def _finding(kind: OdfSecurityKind, part: str, target: str | None = None) -> OdfSecurityFinding:
    return OdfSecurityFinding(kind=kind, part=part, target=target)


def _xml_findings(parts: dict[str, PartManifest]) -> list[OdfSecurityFinding]:
    findings: list[OdfSecurityFinding] = []
    for name, metadata in parts.items():
        if not name.lower().endswith(".xml"):
            continue
        root = ElementTree.fromstring(metadata["bytes"], forbid_dtd=True)
        for element in root.iter():
            local = element.tag.rsplit("}", 1)[-1].lower()
            if local in {"script", "event-listener", "event-listeners"}:
                findings.append(_finding("script", name))
            for attribute, target in element.attrib.items():
                if attribute.rsplit("}", 1)[-1] != "href":
                    continue
                parsed = urlsplit(target)
                if parsed.scheme or target.startswith("//"):
                    findings.append(_finding("external_link", name, target))
    return findings


def _parse_manifest(
    raw: bytes, parts: dict[str, PartManifest], media_type: str
) -> tuple[tuple[OdfManifestEntry, ...], tuple[OdfSecurityFinding, ...]]:
    root = ElementTree.fromstring(raw, forbid_dtd=True)
    if root.tag != f"{{{_NS}}}manifest":
        raise _invalid("ODF manifest root or namespace is invalid", "odf_manifest")
    path_key, media_key, version_key = (f"{{{_NS}}}{name}" for name in ("full-path", "media-type", "version"))
    entries: list[OdfManifestEntry] = []
    findings = _xml_findings(parts)
    seen: set[str] = set()
    for element in root:
        if element.tag != f"{{{_NS}}}file-entry":
            raise _invalid("ODF manifest contains an invalid child", "odf_manifest")
        path = _manifest_path(element.attrib.get(path_key, ""))
        if path in seen:
            raise _invalid(f"duplicate ODF manifest path: {path}", "odf_manifest_duplicate")
        seen.add(path)
        encrypted = any(child.tag.rsplit("}", 1)[-1] == "encryption-data" for child in element)
        declared_media = element.attrib.get(media_key, "")
        role = _role(path, declared_media, encrypted)
        metadata = parts.get(path)
        digest = None if metadata is None else metadata["original_sha256"]
        entries.append(OdfManifestEntry(path, declared_media, element.attrib.get(version_key), encrypted, role, digest))
        if encrypted:
            findings.append(_finding("encryption", path))
        role_finding: dict[OdfRole, OdfSecurityKind] = {
            "embedded_object": "embedded_object", "signature": "signature",
            "macro": "macro", "script": "script",
        }
        if role in role_finding:
            findings.append(_finding(role_finding[role], path))
    roots = [entry for entry in entries if entry.full_path == "/"]
    if len(roots) != 1 or roots[0].media_type != media_type:
        raise _invalid("ODF manifest root media type disagrees with mimetype", "odf_manifest_identity")
    declared = {entry.full_path for entry in entries}
    required = {name for name in parts if name != "mimetype" and not name.startswith("META-INF/")}
    missing = sorted(required - declared)
    dangling = sorted(path for path in declared if path != "/" and not path.endswith("/") and path not in parts)
    if missing or dangling or "content.xml" not in declared:
        raise _invalid(f"ODF manifest inventory mismatch; missing={missing}, dangling={dangling}", "odf_manifest_inventory")
    for name in parts:
        lowered = name.lower()
        if lowered.startswith("meta-inf/") and "signature" in lowered:
            findings.append(_finding("signature", name))
        elif re.search(r"/(?:basic|macros?)/", f"/{lowered}"):
            findings.append(_finding("macro", name))
        elif re.search(r"/(?:scripts?)/", f"/{lowered}"):
            findings.append(_finding("script", name))
        elif lowered.startswith("object "):
            findings.append(_finding("embedded_object", name))
    unique = sorted(set(findings), key=lambda item: (item.kind, item.part, item.target or ""))
    return tuple(entries), tuple(unique)


def preflight_odf(path: Path, limits: BasePackageLimits = DEFAULT_LIMITS) -> OdfPreflight:
    source = Path(path)
    package = preflight_package(source, limits)
    odf_format, media_type = _identity(source, package)
    parts = package["parts"]
    raw = parts[_MANIFEST]["bytes"]
    entries, findings = _parse_manifest(raw, parts, media_type)
    inventory_json = json.dumps([{"kind": item.kind, "part": item.part, "target": item.target} for item in findings], sort_keys=True, separators=(",", ":")).encode("ascii")
    loss = {"style_layout", "metadata"}
    role_losses = {"media": "media", "embedded_object": "embedded_objects", "script": "active_content", "macro": "active_content", "signature": "signatures", "encrypted": "encryption", "unknown": "unknown_parts"}
    loss.update(role_losses[entry.role] for entry in entries if entry.role in role_losses)
    if any(item.kind == "external_link" for item in findings):
        loss.add("external_links")
    if odf_format == "ods":
        loss.add("formulas")
    return OdfPreflight("accepted", odf_format, source, package["source_sha256"], media_type, hashlib.sha256(raw).hexdigest(), entries, findings, hashlib.sha256(inventory_json).hexdigest(), tuple(sorted(loss)))


def clone_odf_package(source: Path, output: Path) -> OdfCloneReceipt:
    source, output = Path(source), Path(output)
    result = preflight_odf(source)
    if output.exists() or output.is_symlink():
        raise DocumentError(DocumentErrorCode.OUTPUT_EXISTS, "emit", "output exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=output.parent, prefix=".odf-clone-")
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as incoming, os.fdopen(descriptor, "wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        output_hash = sha256_file(temporary)
        if sha256_file(source) != result.source_sha256 or output_hash != result.source_sha256:
            raise DocumentError(DocumentErrorCode.SOURCE_CHANGED, "emit", "source changed during exact ODF clone")
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise DocumentError(DocumentErrorCode.OUTPUT_EXISTS, "emit", "output exists") from exc
        temporary.unlink()
        return OdfCloneReceipt(result.source_sha256, output_hash, result.manifest_sha256)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise
