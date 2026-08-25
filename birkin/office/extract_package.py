"""Safe deterministic text extraction from OOXML and HWPX packages."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, overload

from birkin.office.safe_xml import ElementTree
from birkin.office.safe_xml import DefusedXmlException

from .errors import DocumentError, DocumentErrorCode
from .package import PartManifest, preflight_package
from .service_types import ExtractedItem

_RESERVED_PREFIXES = frozenset({b"xml", b"xmlns"})
_PREFIX_PATTERN = re.compile(rb"[<\s]/?([A-Za-z_][\w.-]*):[A-Za-z_]")
_XML_DECLARATION = re.compile(rb"^\s*<\?xml[^>]*\?>")


class _Element(Protocol):
    tag: str
    attrib: dict[str, str]
    text: str | None
    @overload
    def get(self, key: str, default: None = None) -> str | None: ...
    @overload
    def get(self, key: str, default: str) -> str: ...
    def iter(self) -> Iterator[_Element]: ...
    def itertext(self) -> Iterator[str]: ...
    def __iter__(self) -> Iterator[_Element]: ...


def _invalid(part: str, message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PACKAGE_INVALID,
        "import",
        message,
        details={"part": part},
    )


def _local(tag: object) -> str:
    return str(tag).rpartition("}")[2]


def _parse(data: bytes, part: str) -> _Element:
    body = _XML_DECLARATION.sub(b"", data, count=1)
    used: set[bytes] = {match.group(1) for match in _PREFIX_PATTERN.finditer(body)}
    declared = b"".join(
        b' xmlns:%s="urn:birkin:prefix:%s"' % (prefix, prefix)
        for prefix in sorted(used - _RESERVED_PREFIXES)
    )
    try:
        return ElementTree.fromstring(
            b"<birkin-part" + declared + b">" + body + b"</birkin-part>",
            forbid_dtd=True,
        )
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise _invalid(part, f"malformed XML in {part}: {exc}") from exc


def _package_parts(path: Path) -> dict[str, bytes]:
    parts: dict[str, PartManifest] = preflight_package(path)["parts"]
    ordered = sorted(parts.items(), key=lambda item: item[1]["index"])
    return {part_uri: metadata["bytes"] for part_uri, metadata in ordered}


def _numbered(parts: dict[str, bytes], pattern: str) -> list[str]:
    matcher = re.compile(pattern)
    matched = [(match, name) for name in parts if (match := matcher.fullmatch(name))]
    return [name for _, name in sorted(matched, key=lambda pair: int(pair[0].group(1)))]


def _relationship_targets(data: bytes | None, base: str) -> dict[str, str]:
    if data is None:
        return {}
    targets: dict[str, str] = {}
    for node in _parse(data, f"{base}_rels").iter():
        if _local(node.tag) != "Relationship":
            continue
        rel_id = node.get("Id")
        target = node.get("Target")
        if not rel_id or not target or node.get("TargetMode") == "External":
            continue
        targets[rel_id] = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(base + target)
        )
    return targets


def _ordered_parts(
    parts: dict[str, bytes],
    source: str,
    rels: str,
    base: str,
    reference: str,
    fallback: str,
) -> list[str]:
    document = parts.get(source)
    targets = _relationship_targets(parts.get(rels), base)
    if document is None or not targets:
        return _numbered(parts, fallback)
    ordered: list[str] = []
    for node in _parse(document, source).iter():
        if _local(node.tag) != reference:
            continue
        rel_id = next(
            (value for key, value in node.attrib.items() if key.endswith("}id")),
            None,
        )
        target = targets.get(rel_id or "")
        if target is not None and target in parts and target not in ordered:
            ordered.append(target)
    return ordered or _numbered(parts, fallback)


MAX_EXTRACTED_TEXT_BYTES = 10_000_000


def _grouped_text(
    data: bytes,
    part: str,
    paragraph: str,
    text: str,
    budget: list[int] | None = None,
) -> list[str]:
    budget = budget if budget is not None else [MAX_EXTRACTED_TEXT_BYTES]
    lines: list[str] = []
    group: list[str] = []

    def flush() -> bool:
        line = "".join(group)
        if not line.strip():
            return True
        size = len(line.encode("utf-8"))
        if size > budget[0]:
            budget[0] = 0
            return False
        lines.append(line)
        budget[0] -= size
        return budget[0] > 0

    for node in _parse(data, part).iter():
        name = _local(node.tag)
        if name == paragraph:
            if group and not flush():
                break
            group = []
        elif name == text:
            group.append("".join(node.itertext()))
    if budget[0] > 0 and group:
        _ = flush()
    return lines


def _paragraphs(
    parts: dict[str, bytes],
    names: list[str],
    missing: str,
    budget: list[int],
) -> list[str]:
    if not names:
        raise _invalid(missing, f"package contains no {missing} parts")
    lines: list[str] = []
    for name in names:
        lines.extend(
            _grouped_text(parts[name], name, "p", "t", budget)
        )
        if budget[0] <= 0:
            break
    return lines


def _extract_docx(parts: dict[str, bytes], budget: list[int]) -> list[str]:
    part = "word/document.xml"
    data = parts.get(part)
    if data is None:
        raise _invalid(part, f"required part is missing: {part}")
    return _grouped_text(data, part, "p", "t", budget)


def _extract_pptx(parts: dict[str, bytes], budget: list[int]) -> list[str]:
    slides = _ordered_parts(
        parts,
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
        "ppt/",
        "sldId",
        r"ppt/slides/slide(\d+)\.xml",
    )
    return _paragraphs(parts, slides, "slide", budget)


def _shared_strings(parts: dict[str, bytes]) -> list[str]:
    data = parts.get("xl/sharedStrings.xml")
    if data is None:
        return []
    return [
        "".join(node.text or "" for node in item.iter() if _local(node.tag) == "t")
        for item in _parse(data, "xl/sharedStrings.xml").iter()
        if _local(item.tag) == "si"
    ]


def _cell_text(cell: _Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(
            node.text or "" for node in cell.iter() if _local(node.tag) == "t"
        )
    raw = next((node.text or "" for node in cell.iter() if _local(node.tag) == "v"), "")
    if kind != "s":
        return raw
    try:
        index = int(raw)
    except ValueError:
        return ""
    return shared[index] if 0 <= index < len(shared) else ""


def _extract_xlsx(parts: dict[str, bytes], budget: list[int]) -> list[str]:
    sheets = _ordered_parts(
        parts,
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
        "xl/",
        "sheet",
        r"xl/worksheets/sheet(\d+)\.xml",
    )
    if not sheets:
        raise _invalid("xl/worksheets", "package contains no worksheet parts")
    shared = _shared_strings(parts)
    lines: list[str] = []
    for name in sheets:
        for row in _parse(parts[name], name).iter():
            if _local(row.tag) != "row":
                continue
            values = [
                _cell_text(cell, shared) for cell in row if _local(cell.tag) == "c"
            ]
            while values and not values[-1].strip():
                del values[-1]
            if values:
                line = "\t".join(values)
                size = len(line.encode("utf-8"))
                if size > budget[0]:
                    budget[0] = 0
                    return lines
                lines.append(line)
                budget[0] -= size
                if budget[0] <= 0:
                    return lines
    return lines


def extract_package_items(
    path: Path,
    format_name: str,
    *,
    max_text_bytes: int = MAX_EXTRACTED_TEXT_BYTES,
) -> list[ExtractedItem]:
    """Extract typed package nodes without executing relationships or content."""
    if max_text_bytes <= 0:
        raise ValueError("max_text_bytes must be positive")
    parts = _package_parts(path)
    budget = [max_text_bytes]
    if format_name == "docx":
        lines, kind = _extract_docx(parts, budget), "paragraph"
    elif format_name == "xlsx":
        lines, kind = _extract_xlsx(parts, budget), "row"
    elif format_name == "pptx":
        lines, kind = _extract_pptx(parts, budget), "slide_paragraph"
    elif format_name == "hwpx":
        sections = _numbered(parts, r"Contents/section(\d+)\.xml")
        lines, kind = (
            _paragraphs(parts, sections, "section", budget),
            "paragraph",
        )
    else:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_FORMAT,
            "probe",
            f"unsupported package format: {format_name}",
        )
    return [
        {
            "text": text,
            "kind": kind,
            "locator": {"format": format_name, "index": index},
            "method": f"{format_name}_package_text",
        }
        for index, text in enumerate(lines, 1)
    ]


def extract_package_text(path: Path, format_name: str) -> list[str]:
    """Compatibility text projection over typed package extraction."""
    return [item["text"] for item in extract_package_items(path, format_name)]
