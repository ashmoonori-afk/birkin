from __future__ import annotations

from .pptx_geometry import ShapeInfo, scripts
from .pptx_relationships import Element, attribute, local
from .pptx_types import AuditWarning, Locator, RelationshipRecord


def declared_fonts(parsed: dict[str, Element]) -> list[str]:
    values = {
        typeface
        for root in parsed.values()
        for item in root.iter()
        if local(item.tag) in {"latin", "ea", "cs", "font"}
        if (typeface := attribute(item, "typeface"))
    }
    return sorted(values)


def _script_declarations(info: ShapeInfo) -> tuple[bool, bool]:
    latin = False
    east_asian = False
    for item in info.element.iter():
        name = local(item.tag)
        typeface = attribute(item, "typeface")
        if name == "latin" and typeface:
            latin = True
        elif name == "ea" and typeface:
            east_asian = True
    return latin, east_asian


def _theme_scripts(parsed: dict[str, Element]) -> tuple[bool, bool]:
    roots = [root for name, root in parsed.items() if name.startswith("ppt/theme/")]
    latin = any(
        local(item.tag) == "latin" and bool(attribute(item, "typeface"))
        for root in roots
        for item in root.iter()
    )
    east_asian = any(
        local(item.tag) == "ea" and bool(attribute(item, "typeface"))
        for root in roots
        for item in root.iter()
    )
    return latin, east_asian


def audit_shape_fonts(
    slide: str,
    info: ShapeInfo,
    parsed: dict[str, Element],
) -> tuple[list[dict[str, str | None]], list[AuditWarning]]:
    uses_latin, uses_east_asian = scripts(info.text)
    local_latin, local_east_asian = _script_declarations(info)
    theme_latin, theme_east_asian = _theme_scripts(parsed)
    missing: list[dict[str, str | None]] = []
    warnings: list[AuditWarning] = []
    checks = (
        ("latin", uses_latin, local_latin or theme_latin),
        ("east_asian", uses_east_asian, local_east_asian or theme_east_asian),
    )
    for script, used, declared in checks:
        if not used or declared:
            continue
        record = {
            "slide": slide,
            "shape": info.name or info.identifier,
            "script": script,
            "reason": f"missing_{script}_font_declaration",
        }
        missing.append(record)
        warnings.append({
            "code": "PPTX_MISSING_FONT_DECLARATION",
            "slide": slide,
            "shape": info.name or info.identifier,
            "locator": Locator(
                part_uri=slide,
                shape_id=info.identifier,
                placeholder_idx=info.placeholder_idx,
            ),
            "bounds": info.bounds,
            "reason": record["reason"] or "missing_font_declaration",
            "evidence": "ooxml_declaration_audit",
        })
    return missing, warnings


def embedded_fonts(
    parsed: dict[str, Element],
    relations: dict[str, dict[str, RelationshipRecord]],
) -> tuple[list[str], list[AuditWarning]]:
    presentation = parsed.get("ppt/presentation.xml")
    if presentation is None:
        return [], []
    embedded: list[str] = []
    warnings: list[AuditWarning] = []
    presentation_relations = relations.get("ppt/presentation.xml", {})
    for item in presentation.iter():
        if local(item.tag) not in {"regular", "bold", "italic", "boldItalic"}:
            continue
        identifier = attribute(item, "id")
        if not identifier:
            continue
        relation = presentation_relations.get(identifier)
        if relation is not None and relation["state"] == "resolved" and relation["target"]:
            embedded.append(relation["target"])
            continue
        warnings.append({
            "code": "PPTX_MISSING_EMBEDDED_FONT",
            "slide": None,
            "shape": None,
            "locator": Locator(
                part_uri="ppt/presentation.xml",
                shape_id=None,
                placeholder_idx=None,
            ),
            "bounds": None,
            "reason": "missing_font_relationship" if relation is None else relation["state"],
            "evidence": "package_relationship",
        })
    return sorted(set(embedded)), warnings
