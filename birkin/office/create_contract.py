"""Shared values for approval-bound DOCX creation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .artifact_serialization import canonical_integrity_json
from .business_templates import prepare_business_content
from .create_content import ParagraphPlan, PresentationPlan, WorkbookPlan, validate_plan
from .errors import DocumentError, DocumentErrorCode
from .export_types import JSONValue
from .extract_contract import MAX_TEXT_BYTES

FORMAT = "docx"
FORMATS = ("docx", "xlsx", "pptx", "hwpx")
VERSION = 1
# C0, DEL, and C1: DOCX text extraction drops every one of them.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
CATEGORY = "office_create"
PAYLOAD_KEYS = frozenset(
    {
        "version",
        "job_id",
        "creation_digest",
        "format",
        "content",
        "content_sha256",
        "outcome",
        "destination",
        "allowlist_root",
        "proposer",
        "overwrite_approved",
        "authority_digest",
        "output_name",
    }
)


@dataclass(frozen=True, slots=True)
class OfficeCreationRequest:
    """Trusted creation intent parsed at a user-facing boundary."""

    request_text: str
    paragraphs: tuple[str, ...]
    outcome: str
    destination: Path
    overwrite_approved: bool = False
    content: Mapping[str, object] | None = None
    format_name: str = FORMAT


@dataclass(frozen=True, slots=True)
class OfficeCreationCaller:
    """Trusted actor and export root supplied outside the model payload."""

    allowlist_root: Path
    actor: str


def creation_error(message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.PRECONDITION_FAILED,
        "office_create",
        message,
    )


def invalid_creation_input(message: str) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.INVALID_INPUT,
        "office_create",
        message,
    )


def required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise creation_error(f"{name} must be a non-empty string")
    return value


def parse_paragraphs(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise creation_error("content paragraphs must be an array")
    paragraphs = tuple(
        required_text(paragraph, "content paragraph") for paragraph in value
    )
    if not paragraphs:
        raise creation_error("content paragraphs must not be empty")
    if any(CONTROL_CHARACTERS.search(paragraph) for paragraph in paragraphs):
        raise invalid_creation_input(
            "문단 하나가 한 줄입니다. 줄바꿈이나 탭 같은 제어 문자는 넣을 수 없습니다."
        )
    # Execution compares the extracted text, which is the paragraphs joined by
    # one newline and truncated at MAX_TEXT_BYTES UTF-8 bytes.
    text_bytes = sum(len(paragraph.encode("utf-8")) for paragraph in paragraphs)
    text_bytes += len(paragraphs) - 1
    if text_bytes > MAX_TEXT_BYTES:
        raise invalid_creation_input(
            f"본문이 너무 깁니다. UTF-8 기준 {MAX_TEXT_BYTES:,}바이트까지만 됩니다."
        )
    return paragraphs


def creation_content(
    paragraphs: tuple[str, ...],
) -> dict[str, JSONValue]:
    return {"paragraphs": list(paragraphs)}


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def parse_creation_content(
    format_name: str, value: object
) -> tuple[dict[str, JSONValue], tuple[str, ...]]:
    if format_name not in FORMATS:
        raise creation_error(f"unsupported creation format: {format_name}")
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise creation_error("creation content must be an object with string keys")
    raw = cast("Mapping[str, object]", value)
    if format_name in {"docx", "hwpx"} and set(raw) == {"paragraphs"}:
        paragraphs = parse_paragraphs(raw.get("paragraphs"))
        content = creation_content(paragraphs)
        _ = validate_plan(format_name, content)
        return content, paragraphs
    prepared, metadata = prepare_business_content(format_name, raw)
    if metadata is None:
        prepared = dict(raw)
    plan = validate_plan(format_name, prepared)
    if isinstance(plan, ParagraphPlan):
        expected = tuple(
            ([plan.title] if plan.title is not None else [])
            + list(plan.paragraphs)
            + [cell for row in plan.table for cell in row]
            + list(plan.bullets)
        )
        _ = parse_paragraphs(expected)
    elif isinstance(plan, WorkbookPlan):
        rows: list[str] = []
        for sheet in plan.sheets:
            for row in sheet.rows:
                values = [_cell_text(cell) for cell in row]
                while values and not values[-1].strip():
                    values.pop()
                if values:
                    rows.append("\t".join(values))
        expected = tuple(rows)
    elif isinstance(plan, PresentationPlan):
        expected = tuple(
            text
            for slide in plan.slides
            for text in (slide.title, slide.body)
            if text
        )
    else:
        raise creation_error("creation content did not produce a supported plan")
    return cast("dict[str, JSONValue]", dict(raw)), expected


def content_sha256(content: Mapping[str, JSONValue]) -> str:
    return hashlib.sha256(canonical_integrity_json(content).encode("utf-8")).hexdigest()


def creation_operations(
    format_name: str,
    approved_content_sha256: str,
    job_id: str,
) -> tuple[dict[str, JSONValue], ...]:
    return (
        {
            "operation": "create",
            "format": format_name,
            "content_sha256": approved_content_sha256,
            "job_id": job_id,
        },
    )
