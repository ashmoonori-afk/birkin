"""Validated XML token spans used without reserializing HWPX parts."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from birkin.office.safe_xml import ElementTree
from birkin.office.safe_xml import DefusedXmlException

from ..errors import DocumentError, DocumentErrorCode

_TOKEN = re.compile(
    rb"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<![^>]*>|<(?:[^>'\"]|'[^']*'|\"[^\"]*\")+>",
    re.DOTALL,
)
_TAG = re.compile(
    rb"<\s*(/?)\s*([A-Za-z_][\w.:-]*)(?:\s(?:[^>'\"]|'[^']*'|\"[^\"]*\")*)?\s*(/?)>",
    re.DOTALL,
)
_ATTR = re.compile(rb"([A-Za-z_][\w.:-]*)\s*=\s*(['\"])(.*?)\2", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ElementSpan:
    qname: bytes
    start: int
    open_end: int
    close_start: int
    end: int

    @property
    def local_name(self) -> str:
        return self.qname.rsplit(b":", 1)[-1].decode("ascii")


def validate_xml(xml: bytes) -> None:
    try:
        _ = ElementTree.fromstring(xml, forbid_dtd=True, forbid_entities=True)
    except (ElementTree.ParseError, DefusedXmlException, UnicodeDecodeError) as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "locate",
            "HWPX XML part is malformed or unsafe",
        ) from exc


def elements(
    xml: bytes,
    local_name: str | None = None,
    *,
    validated: bool = False,
) -> list[ElementSpan]:
    if not validated:
        validate_xml(xml)
    stack: list[tuple[bytes, int, int]] = []
    found: list[ElementSpan] = []
    for token in _TOKEN.finditer(xml):
        raw = token.group()
        match = _TAG.fullmatch(raw)
        if match is None:
            continue
        closing, qname, empty = match.groups()
        if closing:
            if not stack or stack[-1][0] != qname:
                raise DocumentError(
                    DocumentErrorCode.PACKAGE_INVALID,
                    "locate",
                    "HWPX XML element nesting is malformed",
                )
            opened, start, open_end = stack.pop()
            span = ElementSpan(opened, start, open_end, token.start(), token.end())
            if local_name is None or span.local_name == local_name:
                found.append(span)
        elif empty or raw.rstrip().endswith(b"/>"):
            span = ElementSpan(qname, token.start(), token.end(), token.end(), token.end())
            if local_name is None or span.local_name == local_name:
                found.append(span)
        else:
            stack.append((qname, token.start(), token.end()))
    if stack:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID,
            "locate",
            "HWPX XML element nesting is malformed",
        )
    return sorted(found, key=lambda item: item.start)


def attributes(xml: bytes, span: ElementSpan) -> dict[str, str]:
    opening = xml[span.start : span.open_end]
    result: dict[str, str] = {}
    for match in _ATTR.finditer(opening):
        name = match.group(1).rsplit(b":", 1)[-1].decode("ascii")
        try:
            value = html.unescape(match.group(3).decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise DocumentError(
                DocumentErrorCode.PACKAGE_INVALID,
                "locate",
                "HWPX attribute is not UTF-8",
            ) from exc
        if name in result:
            raise DocumentError(
                DocumentErrorCode.PACKAGE_INVALID,
                "locate",
                "HWPX element has duplicate local attribute names",
            )
        result[name] = value
    return result


def contains(outer: ElementSpan, inner: ElementSpan) -> bool:
    return outer.start <= inner.start and inner.end <= outer.end


def opening_local_name(xml: bytes, span: ElementSpan) -> str:
    del xml
    return span.local_name
