"""Surgical DOCX field/content-control mutation and explicit template merge."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from ..errors import DocumentError, DocumentErrorCode
from ..package import clone_package
from .docx_edit_guard import validate_edit_fragment, word_edit_context
from .docx_nodes import story_name
from .ooxml_semantics import Element, attribute, name_is, semantic_nodes
from .ooxml_surgery import package_parts, require_one, splice_fragmented_text

_WORD_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "http://purl.oclc.org/ooxml/wordprocessingml/main",
        "urn:w",
        "w",
    }
)


def _word(element: Element, local_name: str) -> bool:
    return name_is(element, _WORD_NAMESPACES, local_name)


def _word_attribute(element: Element, local_name: str) -> str | None:
    return attribute(element, _WORD_NAMESPACES, local_name)


def _tagged(element: Element, key: str) -> bool:
    return any(
        _word(descendant, "tag")
        and _word_attribute(descendant, "val") == key
        for descendant in element.iter()
    )


def patch_field_parts(
    parts: dict[str, bytes], key: str, value: str, expected_text: str | None
) -> tuple[str, str, str]:
    matches: list[tuple[str, int, int, bytes, str, int]] = []
    refused_parts: set[str] = set()
    complex_match = False
    for name, xml in parts.items():
        story = story_name(name)
        if name != "word/styles.xml" and story is None:
            continue
        nodes = semantic_nodes(xml)
        controls = [
            node
            for node in nodes
            if _word(node.element, "sdt") and _tagged(node.element, key)
        ]
        if name == "word/styles.xml" or story == "comment":
            if controls:
                refused_parts.add(name)
            continue
        for node in controls:
            nested = sum(
                _word(descendant, "sdt") for descendant in node.element.iter()
            )
            matches.append(
                (
                    name,
                    node.start,
                    node.end,
                    node.block,
                    "content_control",
                    nested,
                )
            )
        for node in nodes:
            if not _word(node.element, "fldSimple"):
                continue
            if key in {
                _word_attribute(node.element, "instr"),
                _word_attribute(node.element, "id"),
            }:
                matches.append(
                    (
                        name,
                        node.start,
                        node.end,
                        node.block,
                        "simple_field",
                        0,
                    )
                )
        complex_match = complex_match or any(
            _word(node.element, "instrText")
            and key == "".join(node.element.itertext()).strip()
            for node in nodes
        )
    if refused_parts:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "locate",
            "field target is in a read-only DOCX story",
            details={"operation": "patch_field", "parts": sorted(refused_parts)},
        )
    if not matches and complex_match:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "locate",
            "complex DOCX field result edits are unsupported",
            details={"operation": "patch_field", "field_type": "complex"},
        )
    selected = require_one(
        [
            (part, start, end, block)
            for part, start, end, block, _kind, _nested in matches
        ],
        "DOCX field or content control",
    )
    part, start, end, block = selected
    target = next(match for match in matches if match[:4] == selected)
    target_type, nested_controls = target[4], target[5]
    context = word_edit_context(parts[part], start)
    if context & {"ins", "del", "moveFrom", "moveTo"}:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "locate",
            "revision-contained DOCX field edits are unsupported",
        )
    if "tbl" in context:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "locate",
            "table-contained DOCX field edits are unsupported",
        )
    if target_type == "content_control" and nested_controls != 1:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "locate",
            "nested content controls are unsupported",
        )
    editable = block
    if target_type == "simple_field":
        editable = block[block.find(b">") + 1 : block.rfind(b"</")]
    validate_edit_fragment(editable)
    changed, previous = splice_fragmented_text(
        parts[part], start, end, value, expected_text=expected_text
    )
    parts[part] = changed
    return part, previous, target_type


def patch_field(
    source: Path,
    output: Path,
    key: object,
    value: object,
    *,
    expected_text: str | None,
    expected_source_sha256: str | None,
) -> dict[str, object]:
    if not isinstance(key, str) or not key or not isinstance(value, str):
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "plan",
            "field key must be non-empty and replacement value must be a string",
        )
    parts, digest = package_parts(source, expected_source_sha256)
    part, previous, target_type = patch_field_parts(parts, key, value, expected_text)
    _ = clone_package(source, output, {part: parts[part]})
    return {
        "source_part": part,
        "source_sha256": digest,
        "previous_text": previous,
        "target_type": target_type,
        "calculated": False,
    }


def merge_template(
    template: Path,
    output: Path,
    merge_map: object,
    *,
    expected_template_sha256: str | None,
) -> dict[str, object]:
    if not isinstance(expected_template_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}", expected_template_sha256
    ) is None:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT, "plan", "valid template SHA-256 precondition is required"
        )
    if not isinstance(merge_map, Mapping):
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "merge map must be an object")
    raw_map = cast("Mapping[object, object]", merge_map)
    if not raw_map:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "merge map must not be empty")
    parts, digest = package_parts(template, expected_template_sha256)
    changed_parts: set[str] = set()
    edits: list[dict[str, object]] = []
    for key, raw in raw_map.items():
        if not isinstance(key, str) or not key:
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "merge keys must be non-empty strings")
        expected: str | None = None
        value: object = raw
        if isinstance(raw, Mapping):
            entry = cast("Mapping[object, object]", raw)
            if set(entry) - {"value", "expected_text"} or "value" not in entry:
                raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "merge entries require only value and optional expected_text")
            value, expected_raw = entry["value"], entry.get("expected_text")
            if expected_raw is not None and not isinstance(expected_raw, str):
                raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "expected_text must be a string")
            expected = expected_raw
        if not isinstance(value, str):
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "merge values must be strings")
        part, previous, target_type = patch_field_parts(parts, key, value, expected)
        changed_parts.add(part)
        edits.append({"key": key, "source_part": part, "previous_text": previous, "target_type": target_type})
    _ = clone_package(template, output, {part: parts[part] for part in changed_parts})
    return {"template_sha256": digest, "changed_parts": sorted(changed_parts), "edits": edits, "calculated": False}
