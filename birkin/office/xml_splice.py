from __future__ import annotations

import html
import re
from collections.abc import Mapping

from .errors import DocumentError, DocumentErrorCode
from .xml_tokens import text_tokens

MAX_SPLICE_BYTES = 64 * 1024 * 1024


def _valid_xml_text(value: str) -> bool:
    def valid_codepoint(codepoint: int) -> bool:
        return (
            codepoint in {0x09, 0x0A, 0x0D}
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        )

    return all(valid_codepoint(ord(character)) for character in value)


def resolve_text_span(
    xml: bytes,
    locator: Mapping[str, object],
) -> tuple[int, int]:
    if len(xml) > MAX_SPLICE_BYTES:
        raise DocumentError(
            DocumentErrorCode.LIMIT_EXCEEDED,
            "locate",
            "XML part exceeds splice limit",
        )
    native = locator.get("paragraph_native_id")
    if not isinstance(native, str) or not native:
        raise DocumentError(
            DocumentErrorCode.AMBIGUOUS_LOCATOR,
            "locate",
            "positional-only locator is forbidden",
        )
    pattern = (
        rb'<(?:\w+:)?p\b[^>]*\b(?:\w+:)?paraId=["\']'
        + re.escape(native.encode())
        + rb'["\'][^>]*>.*?</(?:\w+:)?p\s*>'
    )
    paragraphs = list(re.finditer(pattern, xml, re.DOTALL))
    if not paragraphs:
        raise DocumentError(
            DocumentErrorCode.NODE_NOT_FOUND,
            "locate",
            "paragraph not found",
        )
    if len(paragraphs) > 1:
        raise DocumentError(
            DocumentErrorCode.AMBIGUOUS_LOCATOR,
            "locate",
            "paragraph identity is not unique",
        )
    run_index = locator.get("run_index", 1)
    if not isinstance(run_index, int):
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "locate",
            "run_index must be an integer",
        )
    tokens = text_tokens(paragraphs[0].group())
    index = run_index - 1
    if index < 0 or index >= len(tokens):
        raise DocumentError(
            DocumentErrorCode.NODE_NOT_FOUND,
            "locate",
            "run not found",
        )
    token = tokens[index]
    expected_text = locator.get("expected_text")
    if expected_text is not None:
        if not isinstance(expected_text, str):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "locate",
                "expected_text must be a string",
            )
        try:
            current_text = html.unescape(token.raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise DocumentError(
                DocumentErrorCode.PACKAGE_INVALID,
                "locate",
                "target XML text is not UTF-8",
            ) from exc
        if current_text != expected_text:
            raise DocumentError(
                DocumentErrorCode.PRECONDITION_FAILED,
                "locate",
                "target XML text no longer matches locator precondition",
            )
    return paragraphs[0].start() + token.start, paragraphs[0].start() + token.end


def splice_text(
    xml: bytes,
    locator: Mapping[str, object],
    value: str,
) -> bytes:
    if not _valid_xml_text(value):
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "apply",
            "replacement contains an illegal XML character",
        )
    start, end = resolve_text_span(xml, locator)
    replacement = html.escape(value, quote=False).encode()
    return xml[:start] + replacement + xml[end:]
