"""Metadata-only, fail-closed HWPX encryption declaration inventory."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import urlsplit

from birkin.office.safe_xml import ElementTree

from ..package_types import PackageManifest
from .hwpx_types import HwpxEncryptedPart, HwpxEncryptionInventory


class XmlElement(Protocol):
    tag: str
    attrib: dict[str, str]

    def __iter__(self) -> Iterator[XmlElement]: ...

_NS = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
_AES = {
    "http://www.w3.org/2001/04/xmlenc#aes128-cbc": 16,
    "http://www.w3.org/2001/04/xmlenc#aes192-cbc": 24,
    "http://www.w3.org/2001/04/xmlenc#aes256-cbc": 32,
}
_PBKDF2 = f"{_NS}#pbkdf2"
_SHA256_1K = f"{_NS}#sha256-1k"
_SHA256 = "http://www.w3.org/2000/09/xmldsig#sha256"
_MANIFEST = "META-INF/manifest.xml"


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _attribute(element: XmlElement, name: str) -> str | None:
    return element.attrib.get(f"{{{_NS}}}{name}")


def _child(element: XmlElement, name: str) -> XmlElement | None:
    matches = [item for item in element if _local(item.tag) == name]
    return matches[0] if len(matches) == 1 else None


def _decoded(value: str | None, size: int, issue: str, issues: list[str]) -> str | None:
    if value is None:
        issues.append(issue)
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        issues.append(issue)
        return value
    if len(decoded) != size:
        issues.append(issue)
    return value


def _number(value: str | None, issue: str, issues: list[str]) -> int | None:
    try:
        number = int(value or "")
    except ValueError:
        issues.append(issue)
        return None
    if number <= 0:
        issues.append(issue)
    return number


def _unsafe_target(target: str) -> bool:
    parsed = urlsplit(target)
    path = PurePosixPath(target)
    return (
        not target
        or bool(parsed.scheme or parsed.netloc or parsed.query or parsed.fragment)
        or target.startswith(("/", "//"))
        or "\\" in target
        or ".." in path.parts
        or str(path) != target
    )


def _encryption_nodes(entry: XmlElement) -> list[XmlElement]:
    matches: list[XmlElement] = []
    pending = list(reversed(list(entry)))
    while pending:
        descendant = pending.pop()
        if _local(descendant.tag) == "encryption-data":
            matches.append(descendant)
        pending.extend(reversed(list(descendant)))
    return matches


def declared_encryption_targets(raw: bytes) -> tuple[str, ...]:
    """Return conservatively declared targets, including malformed profiles."""
    root = ElementTree.fromstring(raw, forbid_dtd=True)
    targets: list[str] = []
    for entry in root.iter():
        if _local(entry.tag) != "file-entry" or not _encryption_nodes(entry):
            continue
        target = _attribute(entry, "full-path")
        if target:
            targets.append(target)
    return tuple(targets)


def _part_record(
    entry: XmlElement,
    encryption: XmlElement,
    package: PackageManifest,
    seen: set[str],
) -> tuple[HwpxEncryptedPart, list[str]]:
    issues: list[str] = []
    target = _attribute(entry, "full-path") or ""
    if not target:
        issues.append("missing_target")
    elif _unsafe_target(target):
        issues.append("external_target")
    elif target in seen:
        issues.append("duplicate_target")
    seen.add(target)
    metadata = package["parts"].get(target)
    if target and metadata is None and "external_target" not in issues:
        issues.append("missing_target")

    algorithm_node = _child(encryption, "algorithm")
    key_node = _child(encryption, "key-derivation")
    start_node = _child(encryption, "start-key-generation")
    if algorithm_node is None:
        issues.append("malformed_algorithm")
    if key_node is None:
        issues.append("malformed_key_derivation")
    if start_node is None:
        issues.append("malformed_start_key_generation")

    algorithm = None if algorithm_node is None else _attribute(algorithm_node, "algorithm-name")
    key_size_expected = _AES.get(algorithm or "")
    if key_size_expected is None:
        issues.append("unsupported_algorithm")
    iv = None if algorithm_node is None else _decoded(
        _attribute(algorithm_node, "initialisation-vector"), 16, "malformed_initialisation_vector", issues
    )
    derivation = None if key_node is None else _attribute(key_node, "key-derivation-name")
    if derivation != _PBKDF2:
        issues.append("unsupported_key_derivation")
    key_size = None if key_node is None else _number(_attribute(key_node, "key-size"), "malformed_key_size", issues)
    if key_size_expected is not None and key_size != key_size_expected:
        issues.append("malformed_key_size")
    iterations = None if key_node is None else _number(
        _attribute(key_node, "iteration-count"), "malformed_iteration_count", issues
    )
    if iterations is not None and iterations < 1024:
        issues.append("weak_iteration_count")
    salt = None if key_node is None else _decoded(_attribute(key_node, "salt"), 16, "malformed_salt", issues)
    start = None if start_node is None else _attribute(start_node, "start-key-generation-name")
    if start != _SHA256:
        issues.append("unsupported_start_key_generation")
    start_size = None if start_node is None else _number(
        _attribute(start_node, "key-size"), "malformed_start_key_size", issues
    )
    if start_size != 32:
        issues.append("malformed_start_key_size")
    checksum_type = _attribute(encryption, "checksum-type")
    if checksum_type != _SHA256_1K:
        issues.append("unsupported_checksum")
    checksum = _decoded(_attribute(encryption, "checksum"), 32, "malformed_checksum", issues)
    size = _number(_attribute(entry, "size"), "malformed_original_size", issues)

    return {
        "part": target,
        "media_type": _attribute(entry, "media-type"),
        "original_size": size,
        "source_sha256": None if metadata is None else metadata["original_sha256"],
        "algorithm": algorithm,
        "initialisation_vector": iv,
        "key_derivation": derivation,
        "key_size": key_size,
        "iteration_count": iterations,
        "salt": salt,
        "start_key_generation": start,
        "start_key_size": start_size,
        "checksum_type": checksum_type,
        "checksum": checksum,
        "declaration_state": "valid" if not issues else "malformed",
        "issues": sorted(set(issues)),
    }, issues


def inspect_encryption(package: PackageManifest) -> HwpxEncryptionInventory:
    metadata = package["parts"].get(_MANIFEST)
    credential_required = False
    if metadata is None:
        return {
            "encrypted": False, "password_required": credential_required,
            "credential_state": "not_required", "encryption_state": "not_encrypted",
            "encryption_declaration_state": "absent", "encryption_manifest_part": None,
            "encryption_manifest_sha256": None, "encrypted_parts": [], "encryption_issues": [],
        }
    root = ElementTree.fromstring(metadata["bytes"], forbid_dtd=True)
    parents = {child: parent for parent in root.iter() for child in parent}
    declarations = [element for element in root.iter() if _local(element.tag) == "encryption-data"]
    if not declarations:
        return {
            "encrypted": False, "password_required": credential_required,
            "credential_state": "not_required", "encryption_state": "not_encrypted",
            "encryption_declaration_state": "absent", "encryption_manifest_part": _MANIFEST,
            "encryption_manifest_sha256": metadata["original_sha256"], "encrypted_parts": [],
            "encryption_issues": [],
        }
    entries: list[tuple[XmlElement, XmlElement]] = []
    issues: list[str] = []
    spoofed = root.tag != f"{{{_NS}}}manifest"
    for encryption in declarations:
        parent = parents.get(encryption)
        ancestor = parent
        while ancestor is not None and _local(ancestor.tag) != "file-entry":
            ancestor = parents.get(ancestor)
        if ancestor is None:
            issues.append("orphan_encryption_declaration")
            spoofed = True
            continue
        entries.append((ancestor, encryption))
        spoofed |= (
            parent is not ancestor
            or parents.get(ancestor) is not root
            or ancestor.tag != f"{{{_NS}}}file-entry"
            or encryption.tag != f"{{{_NS}}}encryption-data"
        )
    seen: set[str] = set()
    records: list[HwpxEncryptedPart] = []
    if spoofed:
        issues.append("invalid_manifest_namespace")
    for entry, encryption in entries:
        record, part_issues = _part_record(entry, encryption, package, seen)
        records.append(record)
        issues.extend(part_issues)
    credential_required = bool(declarations)
    return {
        "encrypted": True, "password_required": credential_required,
        "credential_state": "required_not_supplied",
        "encryption_state": "unsupported_encryption_state",
        "encryption_declaration_state": "valid" if not issues else "malformed",
        "encryption_manifest_part": _MANIFEST,
        "encryption_manifest_sha256": metadata["original_sha256"],
        "encrypted_parts": records, "encryption_issues": sorted(set(issues)),
    }
