"""Standards-compliant text-first PDF emission."""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .create_content import ParagraphPlan
from .errors import DocumentError, DocumentErrorCode

_MARGIN: Final[float] = 56.0
_LEADING: Final[float] = 16.0
_WRAP_COLUMNS: Final[int] = 88


def _pdf_literal(text: str) -> bytes:
    return (
        text.encode("latin-1")
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )


def _core_pdf(lines: Sequence[str], target: Path) -> None:
    wrapped = [
        line
        for paragraph in lines
        for line in (textwrap.wrap(paragraph, _WRAP_COLUMNS) or [""])
    ]
    lines_per_page = int((842.0 - 2 * _MARGIN) // _LEADING) + 1
    pages = [
        wrapped[index : index + lines_per_page]
        for index in range(0, len(wrapped), lines_per_page)
    ] or [[]]
    font_id = 3 + 2 * len(pages)
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    page_ids: list[int] = []
    for index, page_lines in enumerate(pages):
        page_id = 3 + 2 * index
        content_id = page_id + 1
        page_ids.append(page_id)
        commands: list[bytes] = []
        cursor = 842.0 - _MARGIN
        for line in page_lines:
            commands.append(
                b"BT /F1 12 Tf 56 "
                + f"{cursor:.0f}".encode()
                + b" Td ("
                + _pdf_literal(line)
                + b") Tj ET"
            )
            cursor -= _LEADING
        stream = b"\n".join(commands)
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            + f"/Resources << /Font << /F1 {font_id} 0 R >> >> ".encode()
            + f"/Contents {content_id} 0 R >>".encode()
        )
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    kids = b" ".join(f"{page_id} 0 R".encode() for page_id in page_ids)
    objects[2] = (
        b"<< /Type /Pages /Kids ["
        + kids
        + b"] /Count "
        + str(len(pages)).encode()
        + b" >>"
    )
    document = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (font_id + 1)
    for object_id in range(1, font_id + 1):
        offsets[object_id] = len(document)
        document.extend(f"{object_id} 0 obj\n".encode())
        document.extend(objects[object_id])
        document.extend(b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {font_id + 1}\n".encode())
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        (
            f"trailer\n<< /Size {font_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    _ = target.write_bytes(document)


def write_pdf(plan: ParagraphPlan, target: Path) -> None:
    lines = plan.paragraphs
    if not all(line.isascii() for line in lines):
        raise DocumentError(
            DocumentErrorCode.CAPABILITY_UNAVAILABLE,
            "emit",
            "non-Latin PDF creation requires an approved backend",
            details={
                "format": "pdf",
                "reason": "pdf_non_latin_backend_unavailable",
                "approved_backend_registered": False,
            },
        )
    _core_pdf(lines, target)
