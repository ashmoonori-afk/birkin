"""Strict parsing for OPC relationship parts."""

from __future__ import annotations

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from . import package_types as types

OPC_RELATIONSHIPS_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
_RELATIONSHIPS = f"{{{OPC_RELATIONSHIPS_NAMESPACE}}}Relationships"
_RELATIONSHIP = f"{{{OPC_RELATIONSHIPS_NAMESPACE}}}Relationship"


class RelationshipPartError(ValueError):
    """An OPC relationship part is malformed or namespace-spoofed."""


def external_relationships(
    name: str, data: bytes
) -> list[types.ExternalRelationship]:
    try:
        root = ElementTree.fromstring(data, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise RelationshipPartError from exc
    if root.tag != _RELATIONSHIPS:
        raise RelationshipPartError
    findings: list[types.ExternalRelationship] = []
    identifiers: set[str] = set()
    for relationship in root:
        identifier = relationship.attrib.get("Id", "")
        relation_type = relationship.attrib.get("Type", "")
        target = relationship.attrib.get("Target", "")
        mode = relationship.attrib.get("TargetMode", "Internal")
        if (
            relationship.tag != _RELATIONSHIP
            or not identifier
            or not relation_type
            or not target
            or identifier in identifiers
            or mode not in {"Internal", "External"}
        ):
            raise RelationshipPartError
        identifiers.add(identifier)
        if mode == "External":
            findings.append(
                {
                    "part_uri": name,
                    "relationship_id": identifier,
                    "target": target,
                }
            )
    return findings
