"""Layered byte, semantic, package, and visual document comparison."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from .adapters.catalog import adapter_inventory
from .errors import DocumentError
from .extract import extract_items
from .package import PackageManifest, preflight_package

MAX_SEMANTIC_NODES = 1_000
MAX_SEMANTIC_TEXT_BYTES = 100_000
MAX_PACKAGE_ENTRIES = 10_000


class ByteComparison(TypedDict):
    equal: bool
    left_sha256: str
    right_sha256: str


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare_bytes(left: Path, right: Path) -> ByteComparison:
    left_hash, right_hash = _hash_file(left), _hash_file(right)
    return {"equal": left_hash == right_hash, "left_sha256": left_hash, "right_sha256": right_hash}


def _text_prefix(text: str, maximum: int) -> str:
    return text.encode("utf-8")[:maximum].decode("utf-8", errors="ignore")


def _semantic_ir(path: Path, format_name: str) -> tuple[list[dict[str, object]], bool]:
    items = extract_items(path, format_name)
    nodes: list[dict[str, object]] = []
    used = 0
    truncated = False
    for order, item in enumerate(items, 1):
        if len(nodes) >= MAX_SEMANTIC_NODES:
            truncated = True
            break
        normalized = unicodedata.normalize("NFC", " ".join(item["text"].split()))
        remaining = MAX_SEMANTIC_TEXT_BYTES - used
        if remaining <= 0:
            truncated = True
            break
        text = _text_prefix(normalized, remaining)
        nodes.append({"order": order, "kind": item["kind"], "text": text})
        used += len(text.encode("utf-8"))
        if text != normalized:
            truncated = True
            break
    return nodes, truncated


def _semantic(left: Path, right: Path, left_format: str, right_format: str) -> dict[str, object]:
    limits = {"max_nodes_per_side": MAX_SEMANTIC_NODES, "max_text_bytes_per_side": MAX_SEMANTIC_TEXT_BYTES}
    try:
        left_ir, left_truncated = _semantic_ir(left, left_format)
        right_ir, right_truncated = _semantic_ir(right, right_format)
    except DocumentError as exc:
        return {
            "status": "unavailable", "equal": None, "reason": exc.message,
            "refusal": exc.envelope()["error"], "normalized_ir": None,
            "limits": limits, "truncation": None,
        }
    truncated = left_truncated or right_truncated
    prefixes_equal = left_ir == right_ir
    return {
        "status": "inconclusive" if truncated else "available",
        "equal": False if not prefixes_equal else None if truncated else True,
        "reason": (
            "bounded semantic extraction was truncated before equality could be proven"
            if truncated
            else None
        ),
        "normalized_ir": {"left": left_ir, "right": right_ir}, "limits": limits,
        "truncation": {"left": left_truncated, "right": right_truncated},
        "normalization": "Unicode NFC, collapsed whitespace, source-independent reading order",
    }


def _entry(path: str, left_hash: str | None, right_hash: str | None) -> dict[str, object]:
    return {"path": path, "left_sha256": left_hash, "right_sha256": right_hash}


def _entry_changes(left: PackageManifest, right: PackageManifest) -> dict[str, list[dict[str, object]]]:
    left_parts, right_parts = left["parts"], right["parts"]
    names = sorted(set(left_parts) | set(right_parts))[:MAX_PACKAGE_ENTRIES]
    changes: dict[str, list[dict[str, object]]] = {"changed": [], "added": [], "removed": [], "unchanged": []}
    for name in names:
        left_hash = left_parts[name]["original_sha256"] if name in left_parts else None
        right_hash = right_parts[name]["original_sha256"] if name in right_parts else None
        category = "added" if left_hash is None else "removed" if right_hash is None else "unchanged" if left_hash == right_hash else "changed"
        changes[category].append(_entry(name, left_hash, right_hash))
    return changes


def _subset(
    changes: dict[str, list[dict[str, object]]], predicate: Callable[[str], bool]
) -> dict[str, list[dict[str, object]]]:
    return {key: [item for item in values if predicate(str(item["path"]))] for key, values in changes.items()}


def _package(left: Path, right: Path, left_format: str, right_format: str) -> dict[str, object]:
    limits = {"max_entries_per_comparison": MAX_PACKAGE_ENTRIES, "entry_payloads_returned": False}
    if "pdf" in {left_format, right_format}:
        return {"status": "unavailable", "equal": None, "reason": "package-entry comparison applies only to ZIP package formats", "limits": limits}
    try:
        left_manifest, right_manifest = preflight_package(left), preflight_package(right)
    except DocumentError as exc:
        return {"status": "unavailable", "equal": None, "reason": exc.message, "limits": limits}
    changes = _entry_changes(left_manifest, right_manifest)
    return {
        "status": "available",
        "equal": not changes["changed"] and not changes["added"] and not changes["removed"],
        "entries": changes,
        "relationships": _subset(changes, lambda name: name.lower().endswith(".rels")),
        "content_types": _subset(changes, lambda name: name == "[Content_Types].xml" or name.lower().endswith("content.hpf")),
        "xml": _subset(changes, lambda name: name.lower().endswith((".xml", ".rels"))),
        "limits": limits,
        "truncated": len(set(left_manifest["parts"]) | set(right_manifest["parts"])) > MAX_PACKAGE_ENTRIES,
    }


def _visual_provenance(left_format: str, right_format: str, capabilities: dict[str, dict[str, object]]) -> dict[str, object]:
    formats = sorted({left_format, right_format})
    return {
        "status": "unavailable", "equal": None,
        "reason": "visual comparison was not run because no approved pinned renderer is registered for both inputs",
        "required_engine_provenance": {
            "registry": "office adapter catalog", "formats": formats,
            "capabilities": {name: capabilities.get(name, {}) for name in formats},
            "requirements": ["approved package", "pinned version", "renderer identity", "deterministic settings"],
        },
        "visual_proof": False,
    }


def compare_documents(
    left: Path, right: Path, left_format: str, right_format: str
) -> dict[str, object]:
    """Return independent equality claims; unavailable visual work never aliases semantic work."""
    byte = compare_bytes(left, right)
    semantic = _semantic(left, right, left_format, right_format)
    package = _package(left, right, left_format, right_format)
    capabilities = {
        item["format"]: dict(item["capabilities"]["render"])
        for item in adapter_inventory()
    }
    visual = _visual_provenance(left_format, right_format, capabilities)
    return {
        "operation": "document_diff", "version": 1,
        "left": {"format": left_format, "sha256": byte["left_sha256"]},
        "right": {"format": right_format, "sha256": byte["right_sha256"]},
        "equal": byte["equal"], "byte_equal": byte["equal"],
        "semantic_equal": semantic["equal"], "visual_equal": None,
        "byte": byte, "semantic": semantic, "package": package, "visual": visual,
    }
