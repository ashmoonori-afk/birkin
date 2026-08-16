"""Stable, JSON-safe locators for editable DOCX story nodes."""

import hashlib
import html
import re
from collections.abc import Mapping
from typing import Literal, TypedDict

from ..errors import DocumentError, DocumentErrorCode
from .ooxml_surgery import element_blocks

DocxNodeKind = Literal["paragraph", "run", "table"]


class DocxLocator(TypedDict):
    source_sha256: str
    part: str
    kind: DocxNodeKind
    index: int
    fingerprint: str


class _DocxNodeOptional(TypedDict, total=False):
    parent_id: str | None
    parent_type: str | None


class DocxNode(_DocxNodeOptional):
    locator: DocxLocator
    text: str
    part: str
    story: str
    kind: DocxNodeKind
    index: int
    table_depth: int


_STORY = re.compile(
    r"word/(?:(document)|(header\d+)|(footer\d+)|(footnotes)|(endnotes)|(comments))\.xml"
)
_TEXT = re.compile(
    rb"<w:(?:t|delText)(?:\s[^>]*)?>(.*?)</w:(?:t|delText)\s*>", re.DOTALL
)
_PARENT = re.compile(rb"<w:(footnote|endnote|comment)\b([^>]*)>")
_ID = re.compile(rb"\bw:id\s*=\s*(['\"])(.*?)\1", re.DOTALL)


def story_name(part: str) -> str | None:
    match = _STORY.fullmatch(part)
    if match is None:
        return None
    return next(
        name
        for name, value in zip(
            ("body", "header", "footer", "footnote", "endnote", "comment"),
            match.groups(),
            strict=True,
        )
        if value is not None
    )


def story_parts(parts: dict[str, bytes]) -> list[str]:
    return sorted(name for name in parts if story_name(name) is not None)


def text_of(fragment: bytes) -> str:
    try:
        return "".join(
            html.unescape(match.group(1).decode("utf-8"))
            for match in _TEXT.finditer(fragment)
        )
    except UnicodeDecodeError as exc:
        raise DocumentError(
            DocumentErrorCode.PACKAGE_INVALID, "read", "DOCX text is not UTF-8"
        ) from exc


def _depth(xml: bytes, offset: int, name: bytes) -> int:
    prefix = xml[:offset]
    return len(re.findall(rb"<w:" + name + rb"\b", prefix)) - len(
        re.findall(rb"</w:" + name + rb"\s*>", prefix)
    )


def _parent(xml: bytes, offset: int) -> tuple[str | None, str | None]:
    active: list[tuple[str, str | None]] = []
    token_pattern = re.compile(rb"</?w:(footnote|endnote|comment)\b[^>]*>")
    for token in token_pattern.finditer(xml[:offset]):
        raw = token.group()
        if raw.startswith(b"</"):
            if active:
                _ = active.pop()
            continue
        parent = _PARENT.fullmatch(raw)
        identifier = None
        if parent is not None:
            found = _ID.search(parent.group(2))
            identifier = found.group(2).decode("utf-8") if found else None
        active.append((token.group(1).decode("ascii"), identifier))
    return active[-1] if active else (None, None)


def inventory_nodes(parts: dict[str, bytes], digest: str) -> list[DocxNode]:
    nodes: list[DocxNode] = []
    for part in story_parts(parts):
        xml = parts[part]
        story = story_name(part)
        if story is None:
            continue
        kinds: tuple[tuple[bytes, DocxNodeKind], ...] = (
            (b"w:p", "paragraph"),
            (b"w:r", "run"),
            (b"w:tbl", "table"),
        )
        for qname, kind in kinds:
            for index, (start, _end, block) in enumerate(element_blocks(xml, qname)):
                fingerprint = hashlib.sha256(block).hexdigest()
                parent_type, parent_id = _parent(xml, start)
                locator: DocxLocator = {
                    "source_sha256": digest,
                    "part": part,
                    "kind": kind,
                    "index": index,
                    "fingerprint": fingerprint,
                }
                node: DocxNode = {
                    "locator": locator,
                    "text": text_of(block),
                    "part": part,
                    "story": story,
                    "kind": kind,
                    "index": index,
                    "table_depth": _depth(xml, start, b"tbl"),
                }
                if parent_type is not None:
                    node["parent_type"], node["parent_id"] = parent_type, parent_id
                nodes.append(node)
    return sorted(nodes, key=lambda item: (item["part"], item["kind"], item["index"]))


def resolve_node(
    parts: dict[str, bytes], digest: str, locator: Mapping[str, object]
) -> tuple[DocxNode, int, int, bytes]:
    if locator.get("source_sha256") != digest:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "locate",
            "DOCX locator is bound to a different source hash",
            artifact_sha256=digest,
            locator=dict(locator),
        )
    part, kind, index = locator.get("part"), locator.get("kind"), locator.get("index")
    qnames = {"paragraph": b"w:p", "run": b"w:r", "table": b"w:tbl"}
    if (
        not isinstance(part, str)
        or not isinstance(kind, str)
        or kind not in qnames
        or not isinstance(index, int)
        or isinstance(index, bool)
    ):
        raise DocumentError(DocumentErrorCode.INVALID_INPUT, "locate", "invalid DOCX locator")
    xml = parts.get(part)
    if xml is None or story_name(part) is None:
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "DOCX story part not found")
    blocks = element_blocks(xml, qnames[kind])
    if index < 0 or index >= len(blocks):
        raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "DOCX node not found")
    start, end, block = blocks[index]
    fingerprint = hashlib.sha256(block).hexdigest()
    if locator.get("fingerprint") != fingerprint:
        raise DocumentError(
            DocumentErrorCode.PRECONDITION_FAILED,
            "locate",
            "DOCX node fingerprint no longer matches",
            locator=dict(locator),
        )
    node = next(
        item
        for item in inventory_nodes({part: xml}, digest)
        if item["kind"] == kind and item["index"] == index
    )
    return node, start, end, block
