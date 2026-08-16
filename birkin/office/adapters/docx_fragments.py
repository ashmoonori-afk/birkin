"""DOCX story structure inventory and conservative edit-boundary checks."""

from __future__ import annotations

import html
import re
from collections import defaultdict

from defusedxml.ElementTree import ParseError, fromstring

from ..errors import DocumentError, DocumentErrorCode
from .docx_types import (
    BoundaryRecord,
    ComplexFieldOpen,
    Inventory,
    Point,
    RangeBoundary,
    StructureRecord,
    empty_inventory,
    mark_duplicate_ids,
)
from .ooxml_surgery import element_blocks

_TAG = re.compile(rb"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<[^>]+>", re.DOTALL)
_NAME = re.compile(rb"</?\s*([\w.-]+:)?([\w.-]+)")
_ATTR = re.compile(rb"(?:[\w.-]+:)?([\w.-]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
_RANGE_TAGS = {
    "commentRangeStart": ("comment_range", "start"),
    "commentRangeEnd": ("comment_range", "end"),
    "bookmarkStart": ("bookmark", "start"),
    "bookmarkEnd": ("bookmark", "end"),
    "moveFromRangeStart": ("move_from_range", "start"),
    "moveFromRangeEnd": ("move_from_range", "end"),
    "moveToRangeStart": ("move_to_range", "start"),
    "moveToRangeEnd": ("move_to_range", "end"),
}
_REVISIONS = {"ins", "del", "moveFrom", "moveTo"}

def _attrs(raw: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in _ATTR.finditer(raw):
        try:
            name = match.group(1).decode("ascii")
            result[name] = html.unescape(match.group(3).decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise DocumentError(
                DocumentErrorCode.PACKAGE_INVALID, "inspect", "DOCX XML is not UTF-8"
            ) from exc
    return result


def _stable(part: str, kind: str, native_id: str | None, order: int) -> str:
    identity = native_id if native_id is not None else f"boundary-{order}"
    return f"{part}#{kind}:{identity}"


def _boundary(
    part: str, kind: str, native_id: str | None, edge: str,
    order: int, offset: int, paragraph: int,
) -> BoundaryRecord:
    return {
        "stable_id": _stable(part, "boundary", None, order), "part": part,
        "type": kind, "id": native_id, "edge": edge, "order": order,
        "offset": offset, "paragraph": paragraph,
    }


def _range_record(
    part: str, kind: str, native_id: str | None, points: list[RangeBoundary]
) -> StructureRecord:
    starts = [point for point in points if point["edge"] == "start"]
    ends = [point for point in points if point["edge"] == "end"]
    first = min(points, key=_point_order)
    reasons: list[str] = []
    if native_id is None:
        reasons.append("missing_id")
    if len(starts) != 1 or len(ends) != 1:
        reasons.append("duplicate_or_missing_boundary")
        reasons += ["duplicate_id"] if len(starts) > 1 or len(ends) > 1 else []
    if starts and ends and starts[0]["order"] > ends[0]["order"]:
        reasons.append("end_before_start")
    start = starts[0] if len(starts) == 1 else None
    end = ends[0] if len(ends) == 1 else None
    move = kind.startswith("move_")
    return {
        "stable_id": _stable(part, kind, native_id, first["order"]), "id": native_id,
        "type": kind, "part": part,
        "state": "malformed" if reasons else ("unsupported" if move else "valid"),
        "reasons": reasons or (["move_ranges_are_read_only"] if move else []),
        "range": {"start": start, "end": end,
                  "zero_length": bool(start and end and end["order"] == start["order"] + 1),
                  "cross_paragraph": bool(start and end and start["paragraph"] != end["paragraph"])},
        "boundaries": sorted(points, key=_point_order),
    }


def _point_order(point: Point) -> int:
    return point["order"]


def inventory_part(part: str, xml: bytes) -> Inventory:
    try:
        _ = fromstring(xml)
    except ParseError as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID, "inspect", f"malformed DOCX story part: {part}"
        ) from exc
    ranges: dict[tuple[str, str | None], list[RangeBoundary]] = defaultdict(list)
    result = empty_inventory()
    order = paragraph = -1
    elements: list[tuple[str, int, int, dict[str, str]]] = []
    revisions: list[str] = []
    complex_fields: list[ComplexFieldOpen] = []
    for token in _TAG.finditer(xml):
        raw = token.group()
        match = _NAME.match(raw)
        if match is None or raw.startswith((b"<!--", b"<![CDATA", b"<?")):
            continue
        name = match.group(2).decode("ascii")
        closing, empty, attrs = raw.startswith(b"</"), raw.rstrip().endswith(b"/>"), _attrs(raw)
        if not closing and name == "p":
            paragraph += 1
        if closing:
            order = _close_element(part, result, elements, revisions, name, token.end(), paragraph, order)
            continue
        if name in _RANGE_TAGS:
            kind, edge = _RANGE_TAGS[name]
            order += 1
            range_point: RangeBoundary = {"order": order, "edge": edge,
                                          "offset": token.start(), "paragraph": paragraph}
            ranges[(kind, attrs.get("id"))].append(range_point)
            result["boundaries"].append(_boundary(
                part, kind, attrs.get("id"), edge, order, token.start(), paragraph
            ))
        elif name == "fldChar":
            order += 1
            field_point: Point = {"order": order, "offset": token.start(), "paragraph": paragraph}
            field_type = attrs.get("fldCharType")
            result["boundaries"].append(_boundary(
                part, "complex_field", None, field_type or "missing", order, token.start(), paragraph
            ))
            _field_boundary(part, result, complex_fields, field_type, field_point)
        if name in _REVISIONS:
            order += 1
            result["boundaries"].append(_boundary(
                part, "tracked_change", attrs.get("id"), "start", order, token.start(), paragraph
            ))
            nested = bool(revisions)
            revisions.append(name)
            elements.append((name, token.start(), order, attrs))
            if nested:
                attrs["nested"] = "true"
        elif name in {"fldSimple", "sdt"}:
            order += 1
            elements.append((name, token.start(), order, attrs))
        elif not empty:
            elements.append((name, token.start(), order, attrs))
    for field in complex_fields:
        result["fields"].append(_malformed_field(part, field["start"], "missing_end"))
    for (kind, native_id), points in ranges.items():
        target = _range_record(part, kind, native_id, points)
        if kind == "comment_range":
            result["comment_ranges"].append(target)
        elif kind == "bookmark":
            result["bookmarks"].append(target)
        else:
            result["tracked_changes"].append(target)
    _simple_and_controls(part, xml, result)
    mark_duplicate_ids(result)
    result["boundaries"].sort(key=_point_order)
    return result


def _close_element(
    part: str, result: Inventory, elements: list[tuple[str, int, int, dict[str, str]]],
    revisions: list[str], name: str, end: int, paragraph: int, order: int,
) -> int:
    for index in range(len(elements) - 1, -1, -1):
        opened, start, start_order, attrs = elements[index]
        if opened != name:
            continue
        del elements[index:]
        if name not in _REVISIONS:
            return order
        _ = revisions.pop()
        order += 1
        native_id = attrs.get("id")
        result["boundaries"].append(_boundary(
            part, "tracked_change", native_id, "end", order, end, paragraph
        ))
        move, nested = name.startswith("move"), attrs.get("nested") == "true"
        reasons = (["move_revision_is_read_only"] if move else []) + (["nested_revision"] if nested else [])
        state = "unsupported" if reasons else "valid"
        if native_id is None:
            state, reasons = "malformed", reasons + ["missing_id"]
        result["tracked_changes"].append({
            "stable_id": _stable(part, "tracked_change", native_id, start_order), "id": native_id,
            "type": name, "part": part, "state": state, "reasons": reasons,
            "range": {"start_order": start_order, "end_order": order,
                      "start_offset": start, "end_offset": end},
        })
        return order
    return order


def _field_boundary(
    part: str, result: Inventory, fields: list[ComplexFieldOpen],
    field_type: str | None, point: Point,
) -> None:
    if field_type == "begin":
        fields.append({"start": point, "separate": None})
    elif field_type == "separate" and fields:
        fields[-1]["separate"] = point
    elif field_type == "end" and fields:
        field = fields.pop()
        start = field["start"]
        result["fields"].append({
            "stable_id": _stable(part, "complex_field", None, start["order"]), "id": None,
            "type": "complex", "part": part, "state": "valid", "reasons": [],
            "range": {"start": start, "separate": field["separate"], "end": point},
        })
    else:
        result["fields"].append(_malformed_field(part, point, f"unexpected_{field_type}"))


def _malformed_field(part: str, point: Point, reason: str) -> StructureRecord:
    return {"stable_id": _stable(part, "complex_field", None, point["order"]), "id": None,
            "type": "complex", "part": part, "state": "malformed", "reasons": [reason],
            "range": {"start": point, "separate": None, "end": None}}


def _simple_and_controls(part: str, xml: bytes, result: Inventory) -> None:
    for qname, kind in ((b"w:fldSimple", "simple"), (b"w:sdt", "content_control")):
        for start, end, block in element_blocks(xml, qname):
            attrs = _attrs(block[: block.find(b">") + 1])
            native_id = attrs.get("id")
            if kind == "content_control":
                tag = re.search(rb"<w:tag\b[^>]*>", block)
                native_id = (_attrs(tag.group()).get("val") if tag else None) or native_id
            boundary_order = sum(1 for boundary in result["boundaries"] if boundary["offset"] < start)
            record: StructureRecord = {
                "stable_id": _stable(part, kind, native_id, boundary_order), "id": native_id,
                "type": kind, "part": part, "instruction": attrs.get("instr"),
                "state": "valid", "reasons": [], "range": {
                    "start_order": boundary_order, "end_order": boundary_order + 1,
                    "start_offset": start, "end_offset": end},
            }
            (result["content_controls"] if kind == "content_control" else result["fields"]).append(record)
