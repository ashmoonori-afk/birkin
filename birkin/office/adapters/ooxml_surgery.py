"""Byte-preserving XML target selection for package adapters."""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from pathlib import Path

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from ..errors import DocumentError, DocumentErrorCode
from ..package import preflight_package
from ..xml_tokens import text_tokens


def package_parts(
    source: Path, expected_source_sha256: str | None
) -> tuple[dict[str, bytes], str]:
    manifest = preflight_package(source)
    digest = manifest["source_sha256"]
    if expected_source_sha256 is not None and digest != expected_source_sha256:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "locate",
            "source hash does not match adapter precondition",
            artifact_sha256=digest,
        )
    return (
        {name: metadata["bytes"] for name, metadata in manifest["parts"].items()},
        digest,
    )


def element_blocks(xml: bytes, qualified_name: bytes) -> list[tuple[int, int, bytes]]:
    try:
        _ = ElementTree.fromstring(xml, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID, "locate", "target XML is malformed"
        ) from exc
    tokens = re.finditer(
        rb"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<[^>]+>", xml, re.DOTALL
    )
    opening = re.compile(rb"<" + re.escape(qualified_name) + rb"\b[^>]*>")
    closing = re.compile(rb"</" + re.escape(qualified_name) + rb"\s*>")
    stack: list[int] = []
    blocks: list[tuple[int, int, bytes]] = []
    for token in tokens:
        raw = token.group()
        if opening.fullmatch(raw) is not None and not raw.rstrip().endswith(b"/>"):
            stack.append(token.start())
        elif closing.fullmatch(raw) is not None:
            if not stack:
                raise DocumentError(
                    DocumentErrorCode.PACKAGE_INVALID,
                    "locate",
                    "target XML element nesting is malformed",
                )
            start = stack.pop()
            blocks.append((start, token.end(), xml[start : token.end()]))
    return sorted(blocks)


def attribute_equals(fragment: bytes, element: bytes, attribute: bytes, value: str) -> bool:
    opening = re.search(rb"<" + re.escape(element) + rb"\b[^>]*>", fragment)
    if opening is None:
        return False
    pattern = (
        rb"\b"
        + re.escape(attribute)
        + rb"\s*=\s*([\"'])"
        + re.escape(value.encode("utf-8"))
        + rb"\1"
    )
    return re.search(pattern, opening.group()) is not None


def require_one(
    matches: Sequence[tuple[str, int, int, bytes]], description: str
) -> tuple[str, int, int, bytes]:
    if not matches:
        raise DocumentError(
            DocumentErrorCode.NODE_NOT_FOUND, "locate", f"{description} not found"
        )
    if len(matches) != 1:
        raise DocumentError(
            DocumentErrorCode.AMBIGUOUS_LOCATOR,
            "locate",
            f"{description} is not unique",
            details={"matches": len(matches)},
        )
    return matches[0]


def splice_fragmented_text(
    xml: bytes,
    start: int,
    end: int,
    value: object,
    *,
    expected_text: str | None,
) -> tuple[bytes, str]:
    if not isinstance(value, str):
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT, "apply", "replacement text must be a string"
        )
    if any(
        ord(character) not in {9, 10, 13}
        and not (0x20 <= ord(character) <= 0xD7FF)
        and not (0xE000 <= ord(character) <= 0xFFFD)
        and not (0x10000 <= ord(character) <= 0x10FFFF)
        for character in value
    ):
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "apply",
            "replacement contains an illegal XML character",
        )
    fragment = xml[start:end]
    tokens = text_tokens(fragment)
    if not tokens:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "locate",
            "target has no directly editable text runs",
        )
    try:
        current = "".join(html.unescape(token.raw.decode("utf-8")) for token in tokens)
    except UnicodeDecodeError as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID, "locate", "target text is not UTF-8"
        ) from exc
    if expected_text is not None and current != expected_text:
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            "locate",
            "target text no longer matches adapter precondition",
            details={"expected_text": expected_text, "actual_text": current},
        )
    replacement = html.escape(value, quote=False).encode("utf-8")
    changed = fragment
    for index, token in reversed(list(enumerate(tokens))):
        payload = replacement if index == 0 else b""
        changed = changed[: token.start] + payload + changed[token.end :]
    return xml[:start] + changed + xml[end:], current
