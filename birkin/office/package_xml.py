"""Bounded XML validation for Office package parts."""

from __future__ import annotations

import re
from typing import final

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .errors import DocumentError, DocumentErrorCode
from .package_types import PackageLimits

_CHUNK_BYTES = 64 * 1024


def _resource(message: str, reason: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.LIMIT_EXCEEDED,
        "import",
        message,
        details={"reason": reason},
    )


def _invalid(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.PACKAGE_INVALID, "import", message)


@final
class _XMLBudget:
    def __init__(self, limits: PackageLimits) -> None:
        self.limits: PackageLimits = limits
        self.nodes = 0
        self.depth = 0
        self.attributes = 0
        self.text_bytes = 0

    def start(self, _tag: str, attributes: dict[str, str]) -> None:
        self.nodes += 1
        self.depth += 1
        self.attributes += len(attributes)
        checks = (
            (self.nodes, self.limits.max_xml_nodes, "xml_nodes"),
            (self.depth, self.limits.max_xml_depth, "xml_depth"),
            (self.attributes, self.limits.max_xml_attributes, "xml_attributes"),
        )
        for actual, maximum, reason in checks:
            if actual > maximum:
                label = reason.removeprefix("xml_")
                raise _resource(f"XML {label} limit exceeded", reason)

    def end(self, _tag: str) -> None:
        self.depth -= 1

    def data(self, text: str) -> None:
        self.text_bytes += len(text.encode("utf-8"))
        if self.text_bytes > self.limits.max_xml_text_bytes:
            raise _resource("XML text byte limit exceeded", "xml_text_bytes")

    def close(self) -> None:
        return None


def _parse_xml(data: bytes, limits: PackageLimits) -> None:
    parser = ElementTree.XMLParser(target=_XMLBudget(limits), forbid_dtd=True)
    for offset in range(0, len(data), _CHUNK_BYTES):
        parser.feed(data[offset : offset + _CHUNK_BYTES])
    _ = parser.close()


def validate_xml(name: str, data: bytes, limits: PackageLimits) -> None:
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", data, re.IGNORECASE):
        raise _invalid("DTD and entities are forbidden")
    try:
        _parse_xml(data, limits)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        kind = "relationship XML" if name.lower().endswith(".rels") else "XML"
        raise _invalid(f"malformed {kind}: {name}") from exc
