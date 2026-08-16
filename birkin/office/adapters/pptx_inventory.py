from __future__ import annotations

import re
from collections.abc import Mapping

from ..errors import DocumentError, DocumentErrorCode
from .pptx_discovery import (
    element_has_table,
    image_relationship,
    placeholder_index,
    shape_identifier,
    shape_nodes,
)
from .pptx_relationships import (
    Element,
    attribute,
    local,
    parse_part,
    relationship_inventory,
)
from .pptx_types import (
    MediaLocator,
    PlaceholderLocator,
    PresentationInventory,
    RelationshipRecord,
    ShapeLocator,
    SlideLocator,
)

_SLIDE = re.compile(r"ppt/slides/slide\d+\.xml")
_IMAGE_OWNER = re.compile(
    r"ppt/(?:slides/slide|notesSlides/notesSlide|slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml"
)
def _descendant(root: Element, name: str) -> Element | None:
    return next((item for item in root.iter() if local(item.tag) == name), None)


def _xml_attribute(opening: bytes, name: bytes) -> str | None:
    match = re.search(rb"\b" + re.escape(name) + rb"\s*=\s*(['\"])(.*?)\1", opening)
    if match is None:
        return None
    try:
        return match.group(2).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentError(DocumentErrorCode.PACKAGE_INVALID, "locate", "PPTX locator attribute is not UTF-8") from exc


def shape_id(block: bytes) -> str | None:
    metadata = re.search(
        rb"<(?:[A-Za-z_][\w.-]*:)?cNvPr\b[^>]*>", block
    )
    return None if metadata is None else _xml_attribute(metadata.group(), b"id")


def shape_blocks(xml: bytes) -> list[tuple[int, int, bytes]]:
    return [(node.start, node.end, node.block) for node in shape_nodes(xml)]


def require_shape(parts: Mapping[str, bytes], part_uri: str, identifier: str) -> tuple[bytes, int, int, bytes]:
    xml = parts.get(part_uri)
    if xml is None or not part_uri.startswith(("ppt/slides/", "ppt/notesSlides/")):
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "PPTX slide or notes part not found", locator={"part_uri": part_uri, "shape_id": identifier})
    matches = [
        (node.start, node.end, node.block)
        for node in shape_nodes(xml)
        if shape_identifier(node.element) == identifier
    ]
    if not matches:
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "PPTX shape not found", locator={"part_uri": part_uri, "shape_id": identifier})
    if len(matches) != 1:
        raise DocumentError(DocumentErrorCode.AMBIGUOUS_LOCATOR, "locate", "PPTX shape identifier is not unique", locator={"part_uri": part_uri, "shape_id": identifier}, details={"matches": len(matches)})
    start, end, block = matches[0]
    return xml, start, end, block


def _slide_locators(
    parsed: Mapping[str, Element],
    by_source: Mapping[str, Mapping[str, RelationshipRecord]],
) -> list[SlideLocator]:
    presentation = parsed.get("ppt/presentation.xml")
    relations = by_source.get("ppt/presentation.xml", {})
    if presentation is None:
        return []
    slides: list[SlideLocator] = []
    for item in presentation.iter():
        if local(item.tag) != "sldId":
            continue
        native_id = item.attrib.get("id", "")
        relationship_ids = [value for key, value in item.attrib.items() if key.endswith("}id")]
        rid = relationship_ids[-1] if relationship_ids else ""
        relation = relations.get(rid)
        target = None if relation is None else relation["target"]
        if target is not None and _SLIDE.fullmatch(target):
            slides.append({"part_uri": target, "relationship_id": rid, "slide_id": native_id})
    return slides


def _relation_target(
    relations: Mapping[str, Mapping[str, RelationshipRecord]],
    part_uri: str,
    rid: str,
) -> str | None:
    relation = relations.get(part_uri, {}).get(rid)
    return None if relation is None else relation["target"]


def presentation_inventory(parts: dict[str, bytes]) -> PresentationInventory:
    parsed = {
        name: parse_part(name, data)
        for name, data in parts.items()
        if name.endswith((".xml", ".rels")) and name.startswith("ppt/")
    }
    _, relations = relationship_inventory(parts, parsed)
    shapes: list[ShapeLocator] = []
    placeholders: list[PlaceholderLocator] = []
    tables: list[ShapeLocator] = []
    charts: list[ShapeLocator] = []
    images: list[MediaLocator] = []
    for part_uri in sorted(name for name in parts if _IMAGE_OWNER.fullmatch(name)):
        is_slide = _SLIDE.fullmatch(part_uri) is not None
        for node in shape_nodes(parts[part_uri]):
            identifier = shape_identifier(node.element)
            if identifier is None:
                continue
            locator: ShapeLocator = {"part_uri": part_uri, "shape_id": identifier}
            if is_slide:
                shapes.append(locator)
                idx = placeholder_index(node.element)
                if idx is not None:
                    placeholders.append({**locator, "placeholder_idx": idx})
                if element_has_table(node.element):
                    tables.append(locator)
                if re.search(rb"<(?:c:)?chart\b", node.block):
                    charts.append(locator)
            image = image_relationship(node.element)
            if image is not None:
                rid, mode = image
                images.append({**locator, "relationship_id": rid, "target_part": _relation_target(relations, part_uri, rid), "mode": mode})
    presentation = parsed.get("ppt/presentation.xml")
    size = None if presentation is None else _descendant(presentation, "sldSz")
    return {
        "slides": _slide_locators(parsed, relations), "shapes": shapes,
        "placeholders": placeholders, "tables": tables, "charts": charts, "images": images,
        "notes": sorted(name for name in parts if name.startswith("ppt/notesSlides/") and name.endswith(".xml")),
        "masters": sorted(name for name in parts if name.startswith("ppt/slideMasters/") and name.endswith(".xml")),
        "layouts": sorted(name for name in parts if name.startswith("ppt/slideLayouts/") and name.endswith(".xml")),
        "themes": sorted(name for name in parts if name.startswith("ppt/theme/") and name.endswith(".xml")),
        "slide_size": {"width_emu": _integer(size, "cx"), "height_emu": _integer(size, "cy")},
    }


def relationship_target_references(
    parts: dict[str, bytes], target_part: str
) -> list[RelationshipRecord]:
    parsed = {
        name: parse_part(name, data)
        for name, data in parts.items()
        if name.endswith(".rels") and name.startswith("ppt/")
    }
    records, _ = relationship_inventory(parts, parsed)
    return [
        record
        for record in records
        if record["target_mode"] == "internal" and record["target"] == target_part
    ]


def _integer(element: Element | None, name: str) -> int | None:
    value = None if element is None else attribute(element, name)
    try:
        return None if value is None else int(value)
    except ValueError:
        return None
