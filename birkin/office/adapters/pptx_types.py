from __future__ import annotations

from typing import Literal, TypedDict


class Bounds(TypedDict):
    x: int
    y: int
    width: int
    height: int
    slide_width: int | None
    slide_height: int | None
    unit: str


class Locator(TypedDict):
    part_uri: str
    shape_id: str | None
    placeholder_idx: str | None


class SlideLocator(TypedDict):
    part_uri: str
    relationship_id: str
    slide_id: str


class ShapeLocator(TypedDict):
    part_uri: str
    shape_id: str


class PlaceholderLocator(TypedDict):
    part_uri: str
    placeholder_idx: str
    shape_id: str | None


class TableCellLocator(TypedDict):
    part_uri: str
    shape_id: str
    row_index: int
    column_index: int


class MediaLocator(TypedDict):
    part_uri: str
    shape_id: str
    relationship_id: str
    target_part: str | None
    mode: Literal["embedded", "linked"]


class AuditWarning(TypedDict):
    code: str
    slide: str | None
    shape: str | None
    locator: Locator
    bounds: Bounds | None
    reason: str
    evidence: str


class MediaRecord(TypedDict):
    slide: str
    shape: str | None
    relationship_id: str
    mode: str
    target: str | None
    state: str


class RelationshipRecord(TypedDict):
    source_part: str
    relationship_id: str
    relationship_type: str
    target: str | None
    target_mode: str
    state: str


class FontInventory(TypedDict):
    declared: list[str]
    embedded: list[str]
    missing_declarations: list[dict[str, str | None]]
    availability: str
    availability_reason: str


class GraphInventory(TypedDict):
    relationships: list[RelationshipRecord]
    broken_relationships: list[RelationshipRecord]
    masters: list[str]
    layouts: list[str]
    themes: list[str]
    notes: list[str]


class VisualVerification(TypedDict):
    state: str
    reason: str


class PptxAudit(TypedDict):
    warnings: list[AuditWarning]
    fonts: FontInventory
    media: list[MediaRecord]
    graph: GraphInventory
    method: str
    visual_verification: VisualVerification


class PreservationRecord(TypedDict):
    unchanged_parts: int
    unchanged_sha256_verified: bool
    relationships_preserved: bool
    masters_preserved: bool
    layouts_preserved: bool
    themes_preserved: bool
    notes_preserved: bool
    media_preserved: bool
    intentionally_changed: list[str]


class OperationEvidence(TypedDict):
    operation: str
    status: Literal["applied"]
    source_sha256: str
    changed_parts: list[str]
    before_sha256: dict[str, str]
    after_sha256: dict[str, str]
    preservation: PreservationRecord
    loss: dict[str, object]
    visual_verification: VisualVerification


class PresentationInventory(TypedDict):
    slides: list[SlideLocator]
    shapes: list[ShapeLocator]
    placeholders: list[PlaceholderLocator]
    tables: list[ShapeLocator]
    charts: list[ShapeLocator]
    images: list[MediaLocator]
    notes: list[str]
    masters: list[str]
    layouts: list[str]
    themes: list[str]
    slide_size: dict[str, int | None]
