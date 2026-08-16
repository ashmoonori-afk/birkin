"""Strict validation and typed normalization for document creation plans."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from .errors import DocumentError, DocumentErrorCode

CellValue = str | int | float | bool | None
Content = Mapping[str, object]
_MAX_PARAGRAPHS: Final = 10_000
_MAX_PARAGRAPH_CHARS: Final = 100_000
_MAX_SHEETS: Final = 256
_MAX_ROWS: Final = 100_000
_MAX_COLUMNS: Final = 16_384
_MAX_SLIDES: Final = 10_000
_BAD_SHEET_NAME: Final = re.compile(r"[\\/*?:\[\]]")


@dataclass(frozen=True)
class ParagraphPlan:
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class SheetPlan:
    name: str
    rows: tuple[tuple[CellValue, ...], ...]


@dataclass(frozen=True)
class WorkbookPlan:
    sheets: tuple[SheetPlan, ...]


@dataclass(frozen=True)
class SlidePlan:
    title: str
    body: str | None


@dataclass(frozen=True)
class PresentationPlan:
    slides: tuple[SlidePlan, ...]


CreatePlan = ParagraphPlan | WorkbookPlan | PresentationPlan


def invalid_content(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", message)


def as_content(value: object, label: str) -> Content:
    if not isinstance(value, Mapping):
        raise invalid_content(f"{label} must be an object")
    raw = cast("Mapping[object, object]", value)
    if any(not isinstance(key, str) for key in raw):
        raise invalid_content(f"{label} keys must be strings")
    return cast("Content", value)


def _reject_unknown(content: Content, allowed: frozenset[str], label: str) -> None:
    unknown = sorted(key for key in content if key not in allowed)
    if unknown:
        raise invalid_content(f"{label} has unsupported keys: {unknown}")


def _entries(value: object, label: str, maximum: int) -> list[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise invalid_content(f"{label} must be a list")
    entries = list(value)
    if not entries:
        raise invalid_content(f"{label} must not be empty")
    if len(entries) > maximum:
        raise invalid_content(f"{label} exceeds the {maximum} item limit")
    return entries


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise invalid_content(f"{label} must be a string")
    if len(value) > _MAX_PARAGRAPH_CHARS:
        raise invalid_content(f"{label} exceeds the {_MAX_PARAGRAPH_CHARS} character limit")
    return value


def _paragraph_plan(content: Content, label: str) -> ParagraphPlan:
    _reject_unknown(content, frozenset({"paragraphs"}), f"{label} content")
    values = _entries(content.get("paragraphs"), f"{label} paragraphs", _MAX_PARAGRAPHS)
    return ParagraphPlan(tuple(_text(value, f"{label} paragraph") for value in values))


def _cell(value: object) -> CellValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise invalid_content("xlsx cell must be a finite scalar or null")


def _workbook_plan(content: Content) -> WorkbookPlan:
    _reject_unknown(content, frozenset({"sheets"}), "xlsx content")
    entries = _entries(content.get("sheets"), "xlsx sheets", _MAX_SHEETS)
    sheets: list[SheetPlan] = []
    names: set[str] = set()
    row_count = 0
    for entry in entries:
        sheet = as_content(entry, "xlsx sheet")
        _reject_unknown(sheet, frozenset({"name", "rows"}), "xlsx sheet")
        name = _text(sheet.get("name"), "xlsx sheet name")
        if not name or len(name) > 31 or _BAD_SHEET_NAME.search(name):
            raise invalid_content("xlsx sheet name is empty, too long, or contains a forbidden character")
        folded = name.casefold()
        if folded in names:
            raise invalid_content("xlsx sheet names must be unique (case-insensitive)")
        names.add(folded)
        raw_rows = _entries(sheet.get("rows"), "xlsx rows", _MAX_ROWS)
        row_count += len(raw_rows)
        if row_count > _MAX_ROWS:
            raise invalid_content(f"xlsx workbook exceeds the {_MAX_ROWS} row limit")
        rows: list[tuple[CellValue, ...]] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes)):
                raise invalid_content("xlsx row must be a list")
            if len(raw_row) > _MAX_COLUMNS:
                raise invalid_content(f"xlsx row exceeds the {_MAX_COLUMNS} column limit")
            rows.append(tuple(_cell(cell) for cell in raw_row))
        sheets.append(SheetPlan(name, tuple(rows)))
    return WorkbookPlan(tuple(sheets))


def _presentation_plan(content: Content) -> PresentationPlan:
    _reject_unknown(content, frozenset({"slides"}), "pptx content")
    entries = _entries(content.get("slides"), "pptx slides", _MAX_SLIDES)
    slides: list[SlidePlan] = []
    for entry in entries:
        slide = as_content(entry, "pptx slide")
        _reject_unknown(slide, frozenset({"title", "body"}), "pptx slide")
        title = _text(slide.get("title"), "pptx slide title")
        body = slide.get("body")
        slides.append(SlidePlan(title, None if body is None else _text(body, "pptx slide body")))
    return PresentationPlan(tuple(slides))


def validate_plan(format_name: str, content: Mapping[str, object]) -> CreatePlan:
    normalized = as_content(content, "content")
    if format_name in {"docx", "pdf", "hwpx"}:
        return _paragraph_plan(normalized, format_name)
    if format_name == "xlsx":
        return _workbook_plan(normalized)
    if format_name == "pptx":
        return _presentation_plan(normalized)
    raise invalid_content(f"no blank plan schema for {format_name}")
