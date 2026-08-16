"""Precise records returned by the DOCX fragmented-structure inventory."""

from __future__ import annotations

from collections import Counter
from typing import TypedDict

from ..typing_compat import NotRequired
from .docx_nodes import DocxNode


class Point(TypedDict):
    order: int
    offset: int
    paragraph: int


class RangeBoundary(Point):
    edge: str


class BoundaryRecord(RangeBoundary):
    stable_id: str
    part: str
    type: str
    id: str | None


class StructureRange(TypedDict):
    start: NotRequired[RangeBoundary | Point | None]
    separate: NotRequired[Point | None]
    end: NotRequired[RangeBoundary | Point | None]
    zero_length: NotRequired[bool]
    cross_paragraph: NotRequired[bool]
    start_order: NotRequired[int]
    end_order: NotRequired[int]
    start_offset: NotRequired[int]
    end_offset: NotRequired[int]


class StructureRecord(TypedDict):
    stable_id: str
    id: str | None
    type: str
    part: str
    state: str
    reasons: list[str]
    range: StructureRange
    instruction: NotRequired[str | None]
    boundaries: NotRequired[list[RangeBoundary]]


class IssueRecord(TypedDict):
    stable_id: str
    state: str
    reasons: list[str]


class Inventory(TypedDict):
    comment_ranges: list[StructureRecord]
    bookmarks: list[StructureRecord]
    fields: list[StructureRecord]
    tracked_changes: list[StructureRecord]
    content_controls: list[StructureRecord]
    boundaries: list[BoundaryRecord]


class DocxInspection(Inventory):
    source_sha256: str
    paragraphs: list[DocxNode]
    runs: list[DocxNode]
    tables: list[DocxNode]
    headers: list[str]
    footers: list[str]
    footnotes: list[str]
    endnotes: list[str]
    comments: list[str]
    styles: list[str]
    sections: int
    structures: list[StructureRecord]
    issues: list[IssueRecord]


class ComplexFieldOpen(TypedDict):
    start: Point
    separate: Point | None


def empty_inventory() -> Inventory:
    return {"comment_ranges": [], "bookmarks": [], "fields": [],
            "tracked_changes": [], "content_controls": [], "boundaries": []}


def mark_duplicate_ids(result: Inventory) -> None:
    groups = (result["comment_ranges"], result["bookmarks"], result["fields"],
              result["tracked_changes"], result["content_controls"])
    for records in groups:
        counts = Counter((item["type"], item["id"]) for item in records if item["id"] is not None)
        for item in records:
            identity = item["id"]
            if identity is not None and counts[(item["type"], identity)] > 1:
                item["state"] = "malformed"
                item["reasons"] = sorted(set(item["reasons"] + ["duplicate_id"]))
