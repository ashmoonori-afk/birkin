"""Offline discovery and hashing of active document content."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from defusedxml import ElementTree

from .errors import DocumentError, DocumentErrorCode
from .package import preflight_package


class InventoryItem(TypedDict):
    kind: str
    part: str
    relationship: str | None
    sha256: str
    risk: str


class ActiveContentEvidence(TypedDict):
    source_sha256: str
    inventory_sha256: str
    inventory: list[InventoryItem]
    preservation_modes: list[str]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory_digest(items: list[InventoryItem]) -> str:
    encoded = json.dumps(
        items, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def _item(
    kind: str,
    part: str,
    data: bytes,
    risk: str,
    relationship: str | None = None,
) -> InventoryItem:
    return {
        "kind": kind,
        "part": part,
        "relationship": relationship,
        "sha256": sha256_bytes(data),
        "risk": risk,
    }


def _internal_target(name: str, target: str) -> str:
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    if name == "_rels/.rels":
        base = ""
    else:
        prefix, marker, relation_name = name.rpartition("/_rels/")
        if not marker or not relation_name.endswith(".rels"):
            return ""
        base = posixpath.dirname(posixpath.join(prefix, relation_name[:-5]))
    return posixpath.normpath(posixpath.join(base, target))


def _relation_items(
    name: str, data: bytes, parts: Mapping[str, bytes]
) -> list[InventoryItem]:
    if not name.lower().endswith(".rels"):
        return []
    root = ElementTree.fromstring(data, forbid_dtd=True)
    findings: list[InventoryItem] = []
    for relation in root:
        attributes = relation.attrib
        identifier = attributes.get("Id", "")
        kind = attributes.get("Type", "")
        target = attributes.get("Target", "")
        mode = attributes.get("TargetMode", "Internal")
        kind_lower, target_lower = kind.lower(), target.lower()
        relation_type = kind_lower.rsplit("/", 1)[-1]
        relationship_kind = ""
        risk = ""
        if mode.lower() == "external":
            relationship_kind, risk = "external_link", "external content reference"
        elif "vbaproject" in relation_type or "macro" in relation_type:
            relationship_kind, risk = "macro_relationship", "macro or VBA relationship"
        elif "activex" in relation_type:
            relationship_kind, risk = "active_x_relationship", "ActiveX relationship"
        elif relation_type in {"oleobject", "package"} or "/embeddings/" in target_lower:
            relationship_kind, risk = "ole_relationship", "embedded OLE relationship"
        elif "externallink" in relation_type or "dde" in relation_type:
            relationship_kind, risk = "external_link", "external or DDE relationship"
        elif "digital-signature" in kind_lower or "signature" in relation_type:
            relationship_kind, risk = "signature_relationship", "signature relationship"
        if relationship_kind:
            canonical = json.dumps(
                {
                    "id": identifier,
                    "mode": mode.lower(),
                    "target": target,
                    "type": kind,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            target_part = (
                _internal_target(name, target) if mode.lower() == "internal" else ""
            )
            payload = parts.get(target_part, canonical.encode("utf-8"))
            findings.append(
                _item(relationship_kind, name, payload, risk, canonical)
            )
    return findings


def _part_item(name: str, data: bytes) -> InventoryItem | None:
    lowered = f"/{name.lower()}"
    basename = lowered.rsplit("/", 1)[-1]
    if lowered.endswith("vbaproject.bin") or re.search(
        r"/(?:scripts?|macros?)/", lowered
    ):
        return _item("macro", name, data, "macro or VBA code")
    if "/macrosheets/" in lowered:
        return _item("xlm_macro", name, data, "Excel 4.0 macro sheet")
    if "/activex/" in lowered:
        return _item("active_x", name, data, "ActiveX control")
    if "/embeddings/" in lowered or basename.startswith("ole"):
        return _item("ole", name, data, "embedded OLE object")
    if (
        "_xmlsignatures/" in lowered
        or "digitalsignature" in lowered
        or basename.startswith("signature")
    ):
        return _item("signature", name, data, "digital signature")
    if (
        "encryptioninfo" in lowered
        or "encryptedpackage" in lowered
        or name.lower().endswith(".xml")
        and re.search(rb"<(?:\w+:)?(?:EncryptedData|encryption)\b", data, re.IGNORECASE)
    ):
        return _item("encryption", name, data, "encrypted package state")
    if "/externallinks/" in lowered or basename in {"connections.xml", "connection.xml"}:
        return _item("external_link", name, data, "external link definition")
    if name.lower().endswith((".xml", ".rels")) and re.search(
        rb"(?:DDEAUTO|\bDDE\b|\|[^!<\r\n]{0,512}!)", data, re.IGNORECASE
    ):
        return _item("dde", name, data, "DDE formula or field")
    return None


def package_inventory(path: Path) -> tuple[str, list[InventoryItem]]:
    manifest = preflight_package(path)
    items: list[InventoryItem] = []
    parts = {name: metadata["bytes"] for name, metadata in manifest["parts"].items()}
    for name, metadata in manifest["parts"].items():
        data = metadata["bytes"]
        finding = _part_item(name, data)
        if finding is not None:
            items.append(finding)
        items.extend(_relation_items(name, data, parts))
    return manifest["source_sha256"], items


def pdf_inventory(raw: bytes) -> list[InventoryItem]:
    patterns = (
        ("encryption", rb"/Encrypt\b", "PDF encryption"),
        ("signature", rb"/Type\s*/Sig\b|/ByteRange\s*\[", "PDF signature"),
        ("javascript", rb"/JavaScript\b|/JS\b", "PDF JavaScript"),
        ("external_link", rb"/(?:URI|GoToR|SubmitForm|ImportData)\b", "PDF external action"),
        ("embedded_file", rb"/(?:EmbeddedFiles|EmbeddedFile|EF)\b", "PDF embedded file"),
        ("active_action", rb"/(?:OpenAction|AA|Launch)\b", "PDF automatic action"),
    )
    return [
        _item(kind, "PDF", raw, risk)
        for kind, pattern, risk in patterns
        if re.search(pattern, raw, re.IGNORECASE)
    ]


def encrypted_container(path: Path, raw: bytes) -> list[InventoryItem]:
    ole_encrypted = raw.startswith(bytes.fromhex("d0cf11e0a1b11ae1")) and re.search(
        rb"EncryptionInfo|EncryptedPackage", raw, re.IGNORECASE
    )
    zip_encrypted = any(
        int.from_bytes(raw[match.start() + 6 : match.start() + 8], "little") & 1
        for match in re.finditer(rb"PK\x03\x04", raw)
    )
    if ole_encrypted or zip_encrypted:
        return [_item("encryption", "EncryptedPackage", raw, "encrypted Office package")]
    raise DocumentError(
        DocumentErrorCode.PACKAGE_INVALID,
        "preflight",
        f"unsupported or invalid document package: {path.name}",
    )


def inspect_inventory(path: Path, preservation_mode: str) -> ActiveContentEvidence:
    raw = path.read_bytes()
    if path.suffix.lower() == ".pdf":
        source_sha, items = sha256_bytes(raw), pdf_inventory(raw)
    else:
        try:
            source_sha, items = package_inventory(path)
        except (zipfile.BadZipFile, DocumentError):
            items = encrypted_container(path, raw)
            source_sha = sha256_bytes(raw)
    ordered = sorted(
        items,
        key=lambda item: (
            item["kind"],
            item["part"],
            item["relationship"] or "",
            item["sha256"],
        ),
    )
    return {
        "source_sha256": source_sha,
        "inventory_sha256": inventory_digest(ordered),
        "inventory": ordered,
        "preservation_modes": [preservation_mode],
    }
