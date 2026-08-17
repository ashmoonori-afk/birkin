from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator
from typing import Protocol
from urllib.parse import unquote

from birkin.office.safe_xml import ElementTree
from birkin.office.safe_xml import DefusedXmlException

from ..errors import DocumentError, DocumentErrorCode
from .pptx_types import AuditWarning, Locator, MediaRecord, RelationshipRecord

_RELATIONSHIP_PART = re.compile(r"(?:^|/)_rels/[^/]+\.rels$")
_MEDIA_RELATION = re.compile(r"/(?:image|audio|video|media)$", re.IGNORECASE)


class Element(Protocol):
    tag: str
    attrib: dict[str, str]
    text: str | None

    def iter(self) -> Iterator[Element]: ...
    def itertext(self) -> Iterator[str]: ...
    def __iter__(self) -> Iterator[Element]: ...


def local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def attribute(element: Element, name: str) -> str | None:
    return next((value for key, value in element.attrib.items() if local(key) == name), None)


def parse_part(name: str, data: bytes) -> Element:
    try:
        return ElementTree.fromstring(data, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "inspect",
            f"malformed or namespace-unbound PPTX XML part: {name}",
            details={"part_uri": name},
        ) from exc


def source_for_relationship_part(name: str) -> str:
    directory, filename = posixpath.split(name)
    source_directory = posixpath.dirname(directory)
    return posixpath.join(source_directory, filename[:-5])


def internal_target(source: str, target: str) -> str:
    clean = unquote(target.split("#", 1)[0]).replace("\\", "/")
    if clean.startswith("/"):
        return posixpath.normpath(clean[1:])
    return posixpath.normpath(posixpath.join(posixpath.dirname(source), clean))


def relationship_inventory(
    parts: dict[str, bytes], parsed: dict[str, Element]
) -> tuple[list[RelationshipRecord], dict[str, dict[str, RelationshipRecord]]]:
    records: list[RelationshipRecord] = []
    by_source: dict[str, dict[str, RelationshipRecord]] = {}
    for name, root in parsed.items():
        if _RELATIONSHIP_PART.search(name) is None:
            continue
        source = source_for_relationship_part(name)
        source_records = by_source.setdefault(source, {})
        for relation in root:
            if local(relation.tag) != "Relationship":
                continue
            identifier = attribute(relation, "Id") or ""
            relation_type = attribute(relation, "Type") or ""
            raw_target = attribute(relation, "Target")
            external = (attribute(relation, "TargetMode") or "").lower() == "external"
            target = raw_target if external or raw_target is None else internal_target(source, raw_target)
            if not identifier or raw_target is None:
                state = "malformed"
            elif external:
                state = "external_unverified"
            elif target not in parts:
                state = "missing_target"
            else:
                state = "resolved"
            record: RelationshipRecord = {
                "source_part": source,
                "relationship_id": identifier,
                "relationship_type": relation_type,
                "target": target,
                "target_mode": "external" if external else "internal",
                "state": state,
            }
            records.append(record)
            if identifier:
                source_records[identifier] = record
    return records, by_source


def relationship_warnings(records: list[RelationshipRecord]) -> list[AuditWarning]:
    warnings: list[AuditWarning] = []
    for record in records:
        if record["state"] not in {"malformed", "missing_target"}:
            continue
        source = record["source_part"]
        warning: AuditWarning = {
            "code": "PPTX_BROKEN_RELATIONSHIP",
            "slide": source if source.startswith("ppt/slides/") else None,
            "shape": None,
            "locator": Locator(
                part_uri=source, shape_id=None, placeholder_idx=None
            ),
            "bounds": None,
            "reason": record["state"],
            "evidence": "package_relationship",
        }
        warnings.append(warning)
    return warnings


def media_inventory(
    slide: str,
    root: Element,
    relations: dict[str, RelationshipRecord],
    *,
    shape: str | None = None,
    shape_id: str | None = None,
) -> tuple[list[MediaRecord], list[AuditWarning]]:
    media: list[MediaRecord] = []
    warnings: list[AuditWarning] = []
    for element in root.iter():
        if local(element.tag) not in {"blip", "videoFile", "audioFile", "media"}:
            continue
        for mode in ("embed", "link"):
            identifier = attribute(element, mode)
            if not identifier:
                continue
            relation = relations.get(identifier)
            state = "missing_relationship" if relation is None else relation["state"]
            record: MediaRecord = {
                "slide": slide,
                "shape": shape,
                "relationship_id": identifier,
                "mode": "embedded" if mode == "embed" else "linked",
                "target": None if relation is None else relation["target"],
                "state": state,
            }
            media.append(record)
            reason: str | None = None
            code = "PPTX_MISSING_MEDIA"
            evidence = "package_relationship"
            if relation is None or state in {"malformed", "missing_target"}:
                reason = state
            elif mode == "link":
                code = "PPTX_LINKED_MEDIA_UNVERIFIED"
                reason = "linked_media_not_fetched"
                evidence = "offline_audit"
            if reason is not None:
                warnings.append({
                    "code": code,
                    "slide": slide,
                    "shape": shape,
                    "locator": Locator(
                        part_uri=slide, shape_id=shape_id, placeholder_idx=None
                    ),
                    "bounds": None,
                    "reason": reason,
                    "evidence": evidence,
                })
    return media, warnings


def is_media_relationship(record: RelationshipRecord) -> bool:
    return _MEDIA_RELATION.search(record["relationship_type"]) is not None
