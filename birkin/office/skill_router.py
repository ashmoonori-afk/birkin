"""Deterministic routing for trusted natural-language Office requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

FORMAT_SKILLS = {
    "docx": "word-documents",
    "xlsx": "spreadsheets",
    "pptx": "presentations",
    "pdf": "pdf-documents",
    "hwpx": "korean-hwp-documents",
    "hwp": "korean-hwp-documents",
}
_FORMAT_TERMS = {
    "docx": (
        "docx",
        "microsoft word",
        "word document",
        "word file",
        "워드",
    ),
    "xlsx": (
        "xlsx",
        "excel",
        "spreadsheet",
        "workbook",
        "엑셀",
        "스프레드시트",
        "예산표",
    ),
    "pptx": (
        "pptx",
        "powerpoint",
        "power point",
        "presentation",
        "slide deck",
        "slides",
        "ppt",
        "발표자료",
        "프레젠테이션",
        "슬라이드",
    ),
    "pdf": ("pdf",),
    "hwpx": (
        "hwpx",
        "hwp",
        "hanword",
        "한컴 문서",
        "한글 문서",
    ),
}
_GENERAL_TERMS = (
    "office document",
    "office work",
    "document work",
    "general office",
    "사무 문서",
    "문서 작업",
    "오피스 문서",
)
_EXTENSION = re.compile(r"(?i)(?:^|[^\w])[\w .()-]+?\.(docx|xlsx|pptx|pdf|hwpx|hwp)\b")


@dataclass(frozen=True)
class OfficeSkillRoute:
    """A safe routing decision made only from trusted request metadata."""

    skill_name: str
    format_name: str | None
    inspect_first: bool = True
    write_policy: str = "copy-on-write"
    conflict: bool = False


def _mentioned_formats(text: str) -> set[str]:
    lowered = text.casefold()
    return {
        format_name
        for format_name, terms in _FORMAT_TERMS.items()
        if any(term in lowered for term in terms)
    }


def _artifact_formats(
    text: str,
    artifact_names: tuple[str, ...],
) -> set[str]:
    formats: set[str] = set()
    for name in artifact_names:
        suffix = PurePath(name.strip()).suffix.lower().lstrip(".")
        if suffix in FORMAT_SKILLS:
            formats.add("hwpx" if suffix == "hwp" else suffix)
    for match in _EXTENSION.finditer(text):
        suffix = match.group(1).lower()
        formats.add("hwpx" if suffix == "hwp" else suffix)
    return formats


def route_office_request(
    user_text: str,
    *,
    artifact_names: tuple[str, ...] = (),
    untrusted_document_text: str | None = None,
) -> OfficeSkillRoute | None:
    """Route from user intent and artifact names, never document contents."""

    _ = untrusted_document_text
    explicit = _mentioned_formats(user_text)
    artifacts = _artifact_formats(user_text, artifact_names)
    combined = explicit | artifacts
    conflict = (
        len(combined) > 1
        or bool(explicit and artifacts and explicit != artifacts)
    )
    if conflict:
        return OfficeSkillRoute(
            "office-documents",
            None,
            conflict=True,
        )
    if combined:
        format_name = next(iter(combined))
        return OfficeSkillRoute(
            FORMAT_SKILLS[format_name],
            format_name,
        )
    lowered = user_text.casefold()
    if any(term in lowered for term in _GENERAL_TERMS):
        return OfficeSkillRoute("office-work-os", None)
    return None


__all__ = [
    "FORMAT_SKILLS",
    "OfficeSkillRoute",
    "route_office_request",
]
