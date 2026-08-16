from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .pptx_relationships import Element, attribute, local
from .pptx_types import AuditWarning, Bounds, Locator

_EMU_PER_POINT = 12_700
_KOREAN = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_LATIN = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class ShapeInfo:
    identifier: str | None
    name: str | None
    placeholder_idx: str | None
    placeholder_type: str | None
    bounds: Bounds | None
    text: str
    element: Element


def _first(root: Element, names: set[str]) -> Element | None:
    return next((item for item in root.iter() if local(item.tag) in names), None)


def _integer(element: Element | None, name: str) -> int | None:
    value = None if element is None else attribute(element, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _rotated_bounds(x: int, y: int, width: int, height: int, rotation: int) -> tuple[int, int, int, int]:
    radians = math.radians((rotation / 60_000) % 360)
    rotated_width = round(abs(width * math.cos(radians)) + abs(height * math.sin(radians)))
    rotated_height = round(abs(width * math.sin(radians)) + abs(height * math.cos(radians)))
    return (
        x - (rotated_width - width) // 2,
        y - (rotated_height - height) // 2,
        rotated_width,
        rotated_height,
    )


def shape_info(shape: Element, slide_width: int | None, slide_height: int | None) -> ShapeInfo:
    metadata = _first(shape, {"cNvPr"})
    placeholder = _first(shape, {"ph"})
    transform = _first(shape, {"xfrm"})
    offset = _first(transform, {"off"}) if transform is not None else None
    extent = _first(transform, {"ext"}) if transform is not None else None
    x, y = _integer(offset, "x"), _integer(offset, "y")
    width, height = _integer(extent, "cx"), _integer(extent, "cy")
    bounds: Bounds | None = None
    if x is not None and y is not None and width is not None and height is not None:
        rotation = _integer(transform, "rot") or 0
        x, y, width, height = _rotated_bounds(x, y, width, height, rotation)
        bounds = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "slide_width": slide_width,
            "slide_height": slide_height,
            "unit": "EMU",
        }
    text = "".join(item.text or "" for item in shape.iter() if local(item.tag) == "t")
    return ShapeInfo(
        None if metadata is None else attribute(metadata, "id"),
        None if metadata is None else attribute(metadata, "name"),
        None if placeholder is None else attribute(placeholder, "idx"),
        None if placeholder is None else attribute(placeholder, "type"),
        bounds,
        text,
        shape,
    )


def _warning(code: str, slide: str, info: ShapeInfo, reason: str, evidence: str) -> AuditWarning:
    return {
        "code": code,
        "slide": slide,
        "shape": info.name or info.identifier,
        "locator": Locator(
            part_uri=slide,
            shape_id=info.identifier,
            placeholder_idx=info.placeholder_idx,
        ),
        "bounds": info.bounds,
        "reason": reason,
        "evidence": evidence,
    }


def _outside(bounds: Bounds) -> bool:
    slide_width, slide_height = bounds["slide_width"], bounds["slide_height"]
    return (
        bounds["x"] < 0
        or bounds["y"] < 0
        or (slide_width is not None and bounds["x"] + bounds["width"] > slide_width)
        or (slide_height is not None and bounds["y"] + bounds["height"] > slide_height)
    )


def _text_overflow_risk(info: ShapeInfo) -> bool:
    if not info.text or info.bounds is None:
        return False
    body = _first(info.element, {"bodyPr"})
    if body is not None and _first(body, {"normAutofit", "spAutoFit"}) is not None:
        return False
    font_sizes = [
        _integer(item, "sz")
        for item in info.element.iter()
        if local(item.tag) in {"rPr", "defRPr", "endParaRPr"}
    ]
    size_points = max((size for size in font_sizes if size is not None), default=1800) / 100
    width = info.bounds["width"]
    height = info.bounds["height"]
    if body is not None:
        width -= (_integer(body, "lIns") or 91_440) + (_integer(body, "rIns") or 91_440)
        height -= (_integer(body, "tIns") or 45_720) + (_integer(body, "bIns") or 45_720)
    if width <= 0 or height <= 0:
        return True
    width_points, height_points = width / _EMU_PER_POINT, height / _EMU_PER_POINT
    units = sum(1.0 if _KOREAN.match(char) else 0.55 for char in info.text)
    no_wrap = body is not None and attribute(body, "wrap") == "none"
    if no_wrap:
        return units * size_points > width_points
    line_capacity = max(width_points / (size_points * 0.55), 1)
    estimated_lines = sum(max(1, math.ceil(len(line) / line_capacity)) for line in info.text.split("\n"))
    return estimated_lines * size_points * 1.2 > height_points


def audit_shape(slide: str, info: ShapeInfo) -> list[AuditWarning]:
    warnings: list[AuditWarning] = []
    if info.bounds is not None and _outside(info.bounds):
        warnings.append(_warning("PPTX_SHAPE_OUTSIDE_SLIDE", slide, info, "shape_bounds_cross_slide_bounds", "declared_geometry"))
    body = _first(info.element, {"bodyPr"})
    clipping = body is not None and (
        attribute(body, "vertOverflow") in {"clip", "ellipsis"}
        or attribute(body, "horzOverflow") == "clip"
    )
    if info.text and clipping:
        warnings.append(_warning("PPTX_EXPLICIT_TEXT_CLIPPING", slide, info, "text_body_declares_clipping", "ooxml_declaration"))
    if _text_overflow_risk(info):
        warnings.append(_warning("PPTX_TEXT_OVERFLOW_RISK", slide, info, "estimated_text_extent_exceeds_shape_bounds", "geometry_heuristic_not_visual_proof"))
    if local(info.element.tag) == "graphicFrame" and info.bounds is not None:
        row_height = sum(
            _integer(item, "h") or 0 for item in info.element.iter() if local(item.tag) == "tr"
        )
        if row_height > info.bounds["height"]:
            warnings.append(_warning("PPTX_TABLE_OVERFLOW_RISK", slide, info, "declared_table_row_heights_exceed_frame_height", "declared_geometry"))
    return warnings


def scripts(text: str) -> tuple[bool, bool]:
    return _LATIN.search(text) is not None, _KOREAN.search(text) is not None
