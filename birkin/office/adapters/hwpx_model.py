"""Structural inventory for namespace-rich HWPX section XML."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from ..errors import DocumentError, DocumentErrorCode
from ..xml_tokens import text_tokens
from .hwpx_xml import ElementSpan, attributes, contains, elements

_SECTION = re.compile(r"Contents/section(\d+)\.xml")


@dataclass(frozen=True, slots=True)
class ParagraphNode:
    part: str
    paragraph_id: str | None
    span: ElementSpan
    state: str


@dataclass(frozen=True, slots=True)
class FieldNode:
    part: str
    field_id: str | None
    aliases: frozenset[str]
    kind: str
    start: int
    end: int
    state: str


@dataclass(frozen=True, slots=True)
class TableNode:
    part: str
    table_id: str | None
    span: ElementSpan
    state: str


@dataclass(frozen=True, slots=True)
class CellNode:
    part: str
    table_id: str | None
    row: int | None
    column: int | None
    row_span: int
    column_span: int
    span: ElementSpan
    state: str


@dataclass(frozen=True, slots=True)
class SectionModel:
    part: str
    xml: bytes
    paragraphs: tuple[ParagraphNode, ...]
    fields: tuple[FieldNode, ...]
    tables: tuple[TableNode, ...]
    cells: tuple[CellNode, ...]


def section_names(parts: dict[str, bytes]) -> list[str]:
    matches = [(int(match.group(1)), name) for name in parts if (match := _SECTION.fullmatch(name))]
    return [name for _, name in sorted(matches)]


def decoded_text(fragment: bytes) -> str:
    try:
        return "".join(html.unescape(token.raw.decode("utf-8")) for token in text_tokens(fragment))
    except UnicodeDecodeError as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "locate",
            "HWPX text is not UTF-8",
        ) from exc


def _state(value: str | None, values: list[str | None]) -> str:
    if value is None or value == "":
        return "malformed"
    return "duplicate" if values.count(value) > 1 else "valid"


def _field_kind(value: str | None) -> str:
    normalized = (value or "").upper().replace("-", "_")
    if normalized in {"CLICK_HERE", "PRESS", "PLACEHOLDER"}:
        return "press"
    if "INPUT" in normalized or normalized in {"FORM", "EDIT"}:
        return "input"
    return "field"


def _fields(part: str, xml: bytes) -> tuple[FieldNode, ...]:
    result: list[FieldNode] = []
    simple = elements(xml, "field", validated=True)
    simple_ids = [attributes(xml, span).get("id") for span in simple]
    for span, field_id in zip(simple, simple_ids, strict=True):
        attrs = attributes(xml, span)
        aliases = frozenset(filter(None, (field_id, attrs.get("name"), attrs.get("fieldName"))))
        result.append(FieldNode(part, field_id, aliases, _field_kind(attrs.get("type")), span.start, span.end, _state(field_id, simple_ids)))

    begins = elements(xml, "fieldBegin", validated=True)
    ends = elements(xml, "fieldEnd", validated=True)
    begin_attrs = [attributes(xml, span) for span in begins]
    begin_ids = [attrs.get("id") for attrs in begin_attrs]
    end_records = [(span, attributes(xml, span).get("beginIDRef")) for span in ends]
    for span, attrs, field_id in zip(begins, begin_attrs, begin_ids, strict=True):
        matching = [(end, ref) for end, ref in end_records if ref == field_id and end.start >= span.end]
        state = _state(field_id, begin_ids)
        if len(matching) != 1:
            state = "malformed" if state == "valid" else state
            end_at = span.end
        else:
            end_at = matching[0][0].start
        aliases = frozenset(filter(None, (field_id, attrs.get("name"), attrs.get("fieldName"))))
        result.append(FieldNode(part, field_id, aliases, _field_kind(attrs.get("type")), span.end, end_at, state))
    known_ids = {value for value in begin_ids if value}
    if any(ref is None or ref not in known_ids for _, ref in end_records):
        result.append(FieldNode(part, None, frozenset(), "field", 0, 0, "malformed"))
    return tuple(result)


def scan_section(part: str, xml: bytes) -> SectionModel:
    paragraphs_spans = elements(xml, "p")
    paragraph_ids = [attributes(xml, span).get("id") or attributes(xml, span).get("paraId") for span in paragraphs_spans]
    paragraphs = tuple(
        ParagraphNode(part, native_id, span, _state(native_id, paragraph_ids))
        for span, native_id in zip(paragraphs_spans, paragraph_ids, strict=True)
    )
    table_spans = elements(xml, "tbl", validated=True)
    table_ids = [attributes(xml, span).get("id") for span in table_spans]
    tables = tuple(
        TableNode(part, native_id, span, _state(native_id, table_ids))
        for span, native_id in zip(table_spans, table_ids, strict=True)
    )
    cells: list[CellNode] = []
    for span in elements(xml, "tc", validated=True):
        parent = next((table for table in tables if contains(table.span, span)), None)
        fragment = xml[span.start : span.end]
        address = next((item for item in elements(fragment, "cellAddr", validated=True)), None)
        cell_span = next((item for item in elements(fragment, "cellSpan", validated=True)), None)
        direct = attributes(xml, span)
        addr_attrs = {} if address is None else attributes(xml[span.start : span.end], address)
        span_attrs = {} if cell_span is None else attributes(xml[span.start : span.end], cell_span)
        try:
            row = int(addr_attrs.get("rowAddr", direct.get("row", "")))
            column = int(addr_attrs.get("colAddr", direct.get("column", "")))
        except ValueError:
            row = column = None
        if row is None and (legacy := direct.get("address")):
            match = re.fullmatch(r"([A-Z]+)([1-9]\d*)", legacy.upper())
            if match:
                column = 0
                for char in match.group(1):
                    column = column * 26 + ord(char) - 64
                column -= 1
                row = int(match.group(2)) - 1
        try:
            row_span = int(span_attrs.get("rowSpan", direct.get("rowSpan", "1")))
            column_span = int(span_attrs.get("colSpan", direct.get("colSpan", "1")))
        except ValueError:
            row_span = column_span = 0
        state = "valid" if parent and parent.state == "valid" and row is not None and column is not None and row_span > 0 and column_span > 0 else "malformed"
        cells.append(CellNode(part, None if parent is None else parent.table_id, row, column, row_span, column_span, span, state))
    return SectionModel(part, xml, paragraphs, _fields(part, xml), tables, tuple(cells))


def scan_sections(parts: dict[str, bytes]) -> tuple[SectionModel, ...]:
    return tuple(scan_section(name, parts[name]) for name in section_names(parts))
