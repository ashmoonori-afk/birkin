"""Expanded-QName discovery paired with byte-preserving XML spans."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, cast
from xml.parsers import expat

from birkin.office.safe_xml import ElementTree
from birkin.office.safe_xml import DefusedXmlException

from ..errors import DocumentError, DocumentErrorCode

_SEPARATOR = "\x1f"


class Element(Protocol):
    tag: str
    attrib: dict[str, str]

    def __iter__(self) -> Iterator[Element]: ...
    def iter(self) -> Iterator[Element]: ...
    def itertext(self) -> Iterator[str]: ...


@dataclass(frozen=True, slots=True)
class SemanticNode:
    element: Element
    start: int
    end: int
    block: bytes


def expanded_name(name: str) -> tuple[str, str]:
    if name.startswith("{"):
        namespace, separator, local_name = name[1:].partition("}")
        if separator:
            return namespace, local_name
    return "", name


def name_is(element: Element, namespaces: frozenset[str], local_name: str) -> bool:
    return expanded_name(element.tag) in {
        (namespace, local_name) for namespace in namespaces
    }


def attribute(
    element: Element,
    namespaces: frozenset[str],
    local_name: str,
    *,
    unqualified: bool = False,
) -> str | None:
    accepted = set(namespaces)
    if unqualified:
        accepted.add("")
    return next(
        (
            value
            for raw_name, value in element.attrib.items()
            if expanded_name(raw_name) in {
                (namespace, local_name) for namespace in accepted
            }
        ),
        None,
    )


def _tag_end(xml: bytes, start: int) -> int:
    quote: int | None = None
    for offset in range(start + 1, len(xml)):
        value = xml[offset]
        if quote is None and value in {ord('"'), ord("'")}:
            quote = value
        elif quote == value:
            quote = None
        elif quote is None and value == ord(">"):
            return offset + 1
    raise DocumentError(
        DocumentErrorCode.PACKAGE_INVALID,
        "locate",
        "OOXML element boundary is malformed",
    )


def _expat_name(name: str) -> tuple[str, str]:
    namespace, separator, local_name = name.rpartition(_SEPARATOR)
    return (namespace, local_name) if separator else ("", name)


def semantic_nodes(xml: bytes) -> list[SemanticNode]:
    """Return semantic elements with exact source spans in document order."""
    try:
        parsed = ElementTree.fromstring(xml, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "locate",
            "OOXML target part is malformed",
        ) from exc
    elements = list(cast("Element", cast("object", parsed)).iter())
    names: list[tuple[str, str]] = []
    spans: list[tuple[int, int] | None] = []
    stack: list[tuple[int, int, int]] = []
    parser = expat.ParserCreate(namespace_separator=_SEPARATOR)

    def start(name: str, _attributes: dict[str, str]) -> None:
        offset = parser.CurrentByteIndex
        opening_end = _tag_end(xml, offset)
        index = len(spans)
        names.append(_expat_name(name))
        spans.append(None)
        stack.append((index, offset, opening_end))

    def end(_name: str) -> None:
        if not stack:
            raise DocumentError(
                DocumentErrorCode.PACKAGE_INVALID,
                "locate",
                "OOXML element nesting is malformed",
            )
        index, offset, opening_end = stack.pop()
        closing_start = parser.CurrentByteIndex
        closing_end = (
            opening_end
            if closing_start == opening_end
            else _tag_end(xml, closing_start)
        )
        spans[index] = (offset, closing_end)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        _ = parser.Parse(xml, True)
    except (expat.ExpatError, DocumentError) as exc:
        if isinstance(exc, DocumentError):
            raise
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "locate",
            "OOXML target part is malformed",
        ) from exc
    expected_names = [expanded_name(element.tag) for element in elements]
    if stack or names != expected_names or any(span is None for span in spans):
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "locate",
            "OOXML semantic and byte discovery disagree",
        )
    concrete = cast("list[tuple[int, int]]", spans)
    return [
        SemanticNode(element, start_offset, end_offset, xml[start_offset:end_offset])
        for element, (start_offset, end_offset) in zip(elements, concrete, strict=True)
    ]
