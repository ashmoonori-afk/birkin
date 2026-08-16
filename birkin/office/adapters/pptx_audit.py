from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace

from .pptx_fonts import audit_shape_fonts, declared_fonts, embedded_fonts
from .pptx_geometry import ShapeInfo, audit_shape, shape_info
from .pptx_relationships import (
    Element,
    attribute,
    local,
    media_inventory,
    parse_part,
    relationship_inventory,
    relationship_warnings,
)
from .pptx_types import (
    AuditWarning,
    Bounds,
    GraphInventory,
    MediaRecord,
    PptxAudit,
    RelationshipRecord,
)

_SLIDE = re.compile(r"ppt/slides/slide\d+\.xml")
_GRAPH_PART = re.compile(
    r"ppt/(?:presentation|slides/slide\d+|slideLayouts/slideLayout\d+|"
    + r"slideMasters/slideMaster\d+|notesSlides/notesSlide\d+|theme/theme\d+)\.xml"
)


def _integer(element: Element | None, name: str) -> int | None:
    value = None if element is None else attribute(element, name)
    try:
        return None if value is None else int(value)
    except ValueError:
        return None


def _slide_size(parsed: dict[str, Element]) -> tuple[int | None, int | None]:
    presentation = parsed.get("ppt/presentation.xml")
    if presentation is None:
        return None, None
    size = next((item for item in presentation.iter() if local(item.tag) == "sldSz"), None)
    return _integer(size, "cx"), _integer(size, "cy")


def _shape_elements(root: Element) -> list[Element]:
    return [item for item in root.iter() if local(item.tag) in {"sp", "graphicFrame"}]


def _media_containers(root: Element) -> list[Element]:
    media_tags = {"blip", "videoFile", "audioFile", "media"}
    return [
        item
        for item in root.iter()
        if local(item.tag) in {"pic", "sp", "graphicFrame"}
        and any(local(child.tag) in media_tags for child in item.iter())
    ]


def _shape_metadata(element: Element) -> tuple[str | None, str | None]:
    metadata = next((item for item in element.iter() if local(item.tag) == "cNvPr"), None)
    if metadata is None:
        return None, None
    return attribute(metadata, "id"), attribute(metadata, "name")


def _is_relationship_id(attribute_name: str) -> bool:
    if attribute_name == "r:id":
        return True
    namespace, separator, _ = attribute_name.rpartition("}")
    return bool(separator) and namespace.endswith("/relationships")


def _graph_reference_warnings(
    parsed: dict[str, Element],
    relations_by_source: Mapping[str, Mapping[str, RelationshipRecord]],
) -> list[AuditWarning]:
    warnings: list[AuditWarning] = []
    for name, root in parsed.items():
        if _GRAPH_PART.fullmatch(name) is None:
            continue
        known = relations_by_source.get(name, {})
        identifiers = {
            value
            for item in root.iter()
            for key, value in item.attrib.items()
            if local(key) == "id" and _is_relationship_id(key)
        }
        for identifier in sorted(identifiers - known.keys()):
            warnings.append({
                "code": "PPTX_MISSING_RELATIONSHIP",
                "slide": name if _SLIDE.fullmatch(name) else None,
                "shape": None,
                "locator": {
                    "part_uri": name,
                    "shape_id": None,
                    "placeholder_idx": None,
                },
                "bounds": None,
                "reason": f"relationship_id_not_defined:{identifier}",
                "evidence": "package_relationship",
            })
    return warnings


def _graph_link_warnings(
    parts: dict[str, bytes],
    relations: Mapping[str, Mapping[str, RelationshipRecord]],
) -> list[AuditWarning]:
    requirements = (
        (r"ppt/slides/slide\d+\.xml", "/slideLayout"),
        (r"ppt/slideLayouts/slideLayout\d+\.xml", "/slideMaster"),
        (r"ppt/slideMasters/slideMaster\d+\.xml", "/theme"),
    )
    warnings: list[AuditWarning] = []
    for pattern, suffix in requirements:
        for source in sorted(name for name in parts if re.fullmatch(pattern, name)):
            if any(
                record["relationship_type"].endswith(suffix)
                for record in relations.get(source, {}).values()
            ):
                continue
            warnings.append({
                "code": "PPTX_MISSING_GRAPH_LINK",
                "slide": source if _SLIDE.fullmatch(source) else None,
                "shape": None,
                "locator": {
                    "part_uri": source,
                    "shape_id": None,
                    "placeholder_idx": None,
                },
                "bounds": None,
                "reason": f"missing_required{suffix}_relationship",
                "evidence": "package_relationship",
            })
    return warnings


def _related_part(
    source: str,
    relation_suffix: str,
    relations: Mapping[str, Mapping[str, RelationshipRecord]],
) -> str | None:
    return next((
        record["target"]
        for record in relations.get(source, {}).values()
        if record["relationship_type"].endswith(relation_suffix)
        and record["state"] == "resolved"
    ), None)


def _placeholder_bounds(
    slide: str,
    info: ShapeInfo,
    parsed: dict[str, Element],
    relations: Mapping[str, Mapping[str, RelationshipRecord]],
    width: int | None,
    height: int | None,
) -> Bounds | None:
    part = _related_part(slide, "/slideLayout", relations)
    for relation_suffix in ("/slideMaster", ""):
        if part is None or part not in parsed:
            return None
        for element in _shape_elements(parsed[part]):
            inherited = shape_info(element, width, height)
            same_idx = info.placeholder_idx is not None and inherited.placeholder_idx == info.placeholder_idx
            same_type = info.placeholder_idx is None and info.placeholder_type is not None and inherited.placeholder_type == info.placeholder_type
            if (same_idx or same_type) and inherited.bounds is not None:
                return inherited.bounds
        part = _related_part(part, relation_suffix, relations) if relation_suffix else None
    return None


def audit_presentation(parts: dict[str, bytes]) -> PptxAudit:
    parsed = {
        name: parse_part(name, data)
        for name, data in parts.items()
        if _GRAPH_PART.fullmatch(name) is not None
        or (name.startswith("ppt/") and name.endswith(".rels"))
    }
    relationships, by_source = relationship_inventory(parts, parsed)
    warnings = relationship_warnings(relationships)
    warnings.extend(_graph_reference_warnings(parsed, by_source))
    warnings.extend(_graph_link_warnings(parts, by_source))
    width, height = _slide_size(parsed)
    media: list[MediaRecord] = []
    missing_fonts: list[dict[str, str | None]] = []
    for slide in sorted(name for name in parsed if _SLIDE.fullmatch(name)):
        root = parsed[slide]
        for container in _media_containers(root):
            shape_id, shape_name = _shape_metadata(container)
            found_media, media_warnings = media_inventory(
                slide,
                container,
                by_source.get(slide, {}),
                shape=shape_name or shape_id,
                shape_id=shape_id,
            )
            media.extend(found_media)
            warnings.extend(media_warnings)
        for element in _shape_elements(root):
            info = shape_info(element, width, height)
            if info.bounds is None and (info.placeholder_idx is not None or info.placeholder_type is not None):
                inherited = _placeholder_bounds(slide, info, parsed, by_source, width, height)
                if inherited is not None:
                    info = replace(info, bounds=inherited)
            warnings.extend(audit_shape(slide, info))
            missing, font_warnings = audit_shape_fonts(slide, info, parsed)
            missing_fonts.extend(missing)
            warnings.extend(font_warnings)
    embedded, embedded_warnings = embedded_fonts(parsed, by_source)
    warnings.extend(embedded_warnings)
    graph: GraphInventory = {
        "relationships": relationships,
        "broken_relationships": [
            item for item in relationships if item["state"] in {"malformed", "missing_target"}
        ],
        "masters": sorted(name for name in parts if name.startswith("ppt/slideMasters/") and name.endswith(".xml")),
        "layouts": sorted(name for name in parts if name.startswith("ppt/slideLayouts/") and name.endswith(".xml")),
        "themes": sorted(name for name in parts if name.startswith("ppt/theme/") and name.endswith(".xml")),
        "notes": sorted(name for name in parts if name.startswith("ppt/notesSlides/") and name.endswith(".xml")),
    }
    warnings.sort(key=lambda item: (
        item["slide"] or "",
        item["shape"] or "",
        item["code"],
        item["reason"],
    ))
    return {
        "warnings": warnings,
        "fonts": {
            "declared": declared_fonts(parsed),
            "embedded": embedded,
            "missing_declarations": missing_fonts,
            "availability": "unverified",
            "availability_reason": "system_fonts_not_queried_and_no_font_fetch_performed",
        },
        "media": media,
        "graph": graph,
        "method": "OOXML declarations and geometry heuristic; not visual proof",
        "visual_verification": {
            "state": "not_run",
            "reason": "renderer_unavailable",
        },
    }
