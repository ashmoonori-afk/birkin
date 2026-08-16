"""Semantic OOXML namespace and consumer discovery for PPTX surgery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from .ooxml_semantics import (
    Element,
    SemanticNode,
    attribute,
    name_is,
    semantic_nodes,
)
from .pptx_types import RelationshipRecord

PRESENTATIONML_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/presentationml/2006/main",
        "http://purl.oclc.org/ooxml/presentationml/main",
        "p",
    }
)
DRAWINGML_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/drawingml/2006/main",
        "http://purl.oclc.org/ooxml/drawingml/main",
        "a",
    }
)
RELATIONSHIP_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "http://purl.oclc.org/ooxml/officeDocument/relationships",
        "r",
    }
)
_SHAPE_NAMES = frozenset({"sp", "graphicFrame", "pic", "cxnSp"})


def is_presentation(element: Element, local_name: str) -> bool:
    return name_is(element, PRESENTATIONML_NAMESPACES, local_name)


def is_drawing(element: Element, local_name: str) -> bool:
    return name_is(element, DRAWINGML_NAMESPACES, local_name)


def shape_nodes(xml: bytes) -> list[SemanticNode]:
    return [
        node
        for node in semantic_nodes(xml)
        if any(is_presentation(node.element, name) for name in _SHAPE_NAMES)
    ]


def shape_identifier(shape: Element) -> str | None:
    metadata = next(
        (
            element
            for element in shape.iter()
            if is_presentation(element, "cNvPr")
        ),
        None,
    )
    return None if metadata is None else metadata.attrib.get("id")


def placeholder_index(shape: Element) -> str | None:
    placeholder = next(
        (
            element
            for element in shape.iter()
            if is_presentation(element, "ph")
        ),
        None,
    )
    return None if placeholder is None else placeholder.attrib.get("idx")


def element_has_table(shape: Element) -> bool:
    return any(is_drawing(element, "tbl") for element in shape.iter())


def shape_has_table(root: Element, identifier: str) -> bool:
    matches = [
        shape
        for shape in root.iter()
        if any(is_presentation(shape, name) for name in _SHAPE_NAMES)
        and shape_identifier(shape) == identifier
    ]
    return len(matches) == 1 and element_has_table(matches[0])


def image_relationship(
    shape: Element,
) -> tuple[str, Literal["embedded", "linked"]] | None:
    for element in shape.iter():
        if not is_drawing(element, "blip"):
            continue
        embedded = attribute(
            element, RELATIONSHIP_NAMESPACES, "embed"
        )
        linked = attribute(element, RELATIONSHIP_NAMESPACES, "link")
        if embedded:
            return embedded, "embedded"
        if linked:
            return linked, "linked"
    return None


def drawing_nodes_within(
    xml: bytes,
    local_name: str,
    start: int,
    end: int,
) -> list[SemanticNode]:
    return [
        node
        for node in semantic_nodes(xml)
        if start <= node.start
        and node.end <= end
        and is_drawing(node.element, local_name)
    ]


def media_target_consumers(
    parts: Mapping[str, bytes],
    relations: Mapping[str, Mapping[str, RelationshipRecord]],
    target_part: str,
) -> list[tuple[str, str]]:
    """Return every semantic XML ``r:embed`` use resolving to a media part."""
    consumers: list[tuple[str, str]] = []
    for part_uri, xml in parts.items():
        if not part_uri.endswith(".xml"):
            continue
        for node in semantic_nodes(xml):
            identifier = attribute(
                node.element, RELATIONSHIP_NAMESPACES, "embed"
            )
            if not identifier:
                continue
            relation = relations.get(part_uri, {}).get(identifier)
            if (
                relation is not None
                and relation["target_mode"] == "internal"
                and relation["target"] == target_part
            ):
                consumers.append((part_uri, identifier))
    return consumers
