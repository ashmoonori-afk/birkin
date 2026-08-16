"""Bounded, structure-aware byte edits for HWPX section parts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TypeVar, cast

from ..errors import DocumentError, DocumentErrorCode
from .hwpx_model import FieldNode, SectionModel
from .hwpx_types import CellLocator, ParagraphLocator, TextLocator
from .hwpx_xml import contains, elements
from .ooxml_surgery import splice_fragmented_text


@dataclass(frozen=True, slots=True)
class PlannedEdit:
    part: str
    start: int
    end: int
    value: str
    expected_text: str | None
    label: str
    native_id: str | None = None
    kind: str | None = None


def _section(models: tuple[SectionModel, ...], part: str) -> SectionModel:
    matches = [model for model in models if model.part == part]
    if len(matches) != 1:
        raise DocumentError(
            DocumentErrorCode.NODE_NOT_FOUND,
            "locate",
            "HWPX section locator part was not found",
            locator={"part": part},
        )
    return matches[0]


_T = TypeVar("_T")


def _unique(items: Sequence[_T], label: str) -> _T:
    if not items:
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", f"{label} not found")
    if len(items) != 1:
        raise DocumentError(
            DocumentErrorCode.AMBIGUOUS_LOCATOR,
            "locate",
            f"{label} is not unique",
            details={"matches": len(items)},
        )
    return items[0]


def paragraph_edit(models: tuple[SectionModel, ...], locator: ParagraphLocator, value: str, expected: str | None) -> PlannedEdit:
    model = _section(models, locator.part)
    matches = [item for item in model.paragraphs if item.paragraph_id == locator.paragraph_id]
    paragraph = _unique(matches, "HWPX paragraph id")
    if paragraph.state != "valid":
        raise DocumentError(DocumentErrorCode.AMBIGUOUS_LOCATOR, "locate", "HWPX paragraph id is duplicate or malformed")
    fragment = model.xml[paragraph.span.start : paragraph.span.end]
    if any(elements(fragment, local, validated=True) for local in ("tbl", "field", "fieldBegin", "fieldEnd", "ctrl")):
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "locate",
            "paragraphs containing controls, fields, or tables require a narrower locator",
        )
    return PlannedEdit(model.part, paragraph.span.start, paragraph.span.end, value, expected, "paragraph", paragraph.paragraph_id)


def text_edit(models: tuple[SectionModel, ...], locator: TextLocator, value: str, expected: str | None) -> PlannedEdit:
    if locator.run_index < 0 or locator.text_index < 0:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "locate", "HWPX text indexes must be non-negative")
    model = _section(models, locator.part)
    paragraphs = [item for item in model.paragraphs if item.paragraph_id == locator.paragraph_id]
    selected = _unique(paragraphs, "HWPX paragraph id")
    if selected.state != "valid":
        raise DocumentError(DocumentErrorCode.AMBIGUOUS_LOCATOR, "locate", "HWPX paragraph id is duplicate or malformed")
    runs = [span for span in elements(model.xml, "run") if contains(selected.span, span)]
    if locator.run_index >= len(runs):
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "HWPX run index was not found")
    texts = [span for span in elements(model.xml, "t") if contains(runs[locator.run_index], span)]
    if locator.text_index >= len(texts):
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "HWPX text index was not found")
    span = texts[locator.text_index]
    return PlannedEdit(model.part, span.start, span.end, value, expected, "text", locator.paragraph_id)


def cell_edit(models: tuple[SectionModel, ...], locator: CellLocator, value: str, expected: str | None) -> PlannedEdit:
    model = _section(models, locator.part)
    matches = [item for item in model.cells if item.table_id == locator.table_id and item.row == locator.row and item.column == locator.column]
    selected = _unique(matches, "HWPX table cell")
    if selected.state != "valid":
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "HWPX cell locator or span metadata is malformed")
    fragment = model.xml[selected.span.start : selected.span.end]
    if elements(fragment, "tbl", validated=True):
        raise DocumentError(DocumentErrorCode.UNSUPPORTED_EDIT, "locate", "nested-table cell edits are unsupported")
    if any(elements(fragment, local, validated=True) for local in ("field", "fieldBegin", "fieldEnd", "ctrl")):
        raise DocumentError(DocumentErrorCode.UNSUPPORTED_EDIT, "locate", "cells containing fields or controls require a narrower locator")
    return PlannedEdit(model.part, selected.span.start, selected.span.end, value, expected, "cell", locator.table_id)


def field_edit(
    models: tuple[SectionModel, ...],
    key: str,
    value: str,
    expected: str | None,
    *,
    part: str | None = None,
    native_id_only: bool = False,
) -> PlannedEdit:
    if not key:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "locate", "HWPX field key must be non-empty")
    matches = [
        (model, item)
        for model in models
        for item in model.fields
        if (part is None or model.part == part)
        and (item.field_id == key if native_id_only else key in item.aliases)
    ]
    selected: tuple[SectionModel, FieldNode] = _unique(matches, "HWPX field id or name")
    model, field = selected
    if field.state == "duplicate":
        raise DocumentError(DocumentErrorCode.AMBIGUOUS_LOCATOR, "locate", "HWPX field id is duplicate")
    if field.state != "valid" or field.end <= field.start:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "HWPX field boundary or identifier is malformed")
    overlaps = [
        item
        for item in model.fields
        if item is not field and max(item.start, field.start) < min(item.end, field.end)
    ]
    if overlaps:
        raise DocumentError(DocumentErrorCode.UNSUPPORTED_EDIT, "locate", "nested or overlapping HWPX fields are unsupported")
    return PlannedEdit(model.part, field.start, field.end, value, expected, "field", field.field_id, field.kind)


def binding_values(bindings: Mapping[object, object]) -> list[tuple[str, str, str | None]]:
    if not bindings or len(bindings) > 10_000:
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "HWPX bindings must contain 1 to 10000 entries")
    result: list[tuple[str, str, str | None]] = []
    for key, raw in bindings.items():
        if not isinstance(key, str) or not key:
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", "HWPX binding keys must be non-empty strings")
        if isinstance(raw, str):
            result.append((key, raw, None))
            continue
        if not isinstance(raw, Mapping):
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", f"HWPX binding {key!r} is malformed")
        binding = cast("Mapping[object, object]", raw)
        if set(binding) - {"value", "expected_text"}:
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", f"HWPX binding {key!r} is malformed")
        value, expected = binding.get("value"), binding.get("expected_text")
        if not isinstance(value, str) or (expected is not None and not isinstance(expected, str)):
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", f"HWPX binding {key!r} values must be strings")
        result.append((key, value, expected))
    return result


def apply_edits(parts: dict[str, bytes], edits: list[PlannedEdit]) -> tuple[dict[str, bytes], dict[str, str]]:
    replacements: dict[str, bytes] = {}
    previous: dict[str, str] = {}
    for part in {edit.part for edit in edits}:
        selected = sorted((edit for edit in edits if edit.part == part), key=lambda item: item.start, reverse=True)
        for left, right in pairwise(selected):
            if right.end > left.start:
                raise DocumentError(DocumentErrorCode.UNSUPPORTED_EDIT, "plan", "overlapping HWPX edits are unsupported")
        xml = parts[part]
        for edit in selected:
            xml, old = splice_fragmented_text(xml, edit.start, edit.end, edit.value, expected_text=edit.expected_text)
            previous[edit.label if len(edits) == 1 else cast(str, edit.native_id)] = old
        replacements[part] = xml
    return replacements, previous
