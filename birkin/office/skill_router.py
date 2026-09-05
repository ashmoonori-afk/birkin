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
    ),
    "pptx": (
        "pptx",
        "powerpoint",
        "power point",
        "presentation",
        "slide deck",
        "slides",
        "ppt",
        "파워포인트",
        "피피티",
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
        "한글파일",
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
_DEFAULT_FORMAT_TERMS = {
    "docx": ("보고서", "리포트", "report"),
    "xlsx": ("예산표", "budget sheet"),
}
_RESULT_TERMS = ("만들", "작성", "저장", "요약", "create", "write", "save", "summarize")
FORMAT_CLARIFICATION_QUESTION = "어느 포맷으로 저장할까요?"


@dataclass(frozen=True)
class OfficeSkillRoute:
    """A safe routing decision made only from trusted request metadata."""

    skill_name: str
    format_name: str | None
    source_formats: tuple[str, ...] = ()
    target_format: str | None = None
    target_format_suggested: bool = False
    inspect_first: bool = True
    write_policy: str = "copy-on-write"
    conflict: bool = False
    clarification_question: str | None = None


def _mentioned_formats(text: str) -> set[str]:
    lowered = text.casefold()
    return {
        format_name
        for format_name, terms in _FORMAT_TERMS.items()
        if any(term in lowered for term in terms)
    }


def _artifact_formats(artifact_names: tuple[str, ...]) -> set[str]:
    formats: set[str] = set()
    for name in artifact_names:
        suffix = PurePath(name.strip()).suffix.lower().lstrip(".")
        if suffix in FORMAT_SKILLS:
            formats.add("hwpx" if suffix == "hwp" else suffix)
    return formats


def _role_formats(text: str) -> tuple[set[str], set[str]]:
    lowered = text.casefold()
    sources: set[str] = set()
    targets: set[str] = set()
    for format_name, terms in _FORMAT_TERMS.items():
        for term in terms:
            escaped = re.escape(term)
            if re.search(
                rf"(?:첨부|from)\s*.{{0,12}}{escaped}|{escaped}(?:\s*(?:파일|문서))?(?:을|를)?\s*(?:읽|검토|분석|비교|참고)",
                lowered,
            ):
                sources.add(format_name)
            if re.search(
                rf"{escaped}(?:\s*(?:파일|문서|보고서))?(?:으)?로\s*(?:저장|만들|작성|요약|변환)|(?:save|export|convert|summarize)\s+(?:as|to)\s+{escaped}",
                lowered,
            ):
                targets.add(format_name)
    return sources, targets


def route_office_request(
    user_text: str,
    *,
    artifact_names: tuple[str, ...] = (),
    target_name: str | None = None,
    untrusted_document_text: str | None = None,
) -> OfficeSkillRoute | None:
    """Route from user intent and artifact names, never document contents."""

    _ = untrusted_document_text
    explicit = _mentioned_formats(user_text)
    sources, targets = _role_formats(user_text)
    sources |= _artifact_formats(artifact_names)
    if target_name is not None:
        targets |= _artifact_formats((target_name,))
    unknown = explicit - sources - targets
    creates_result = any(term in user_text.casefold() for term in _RESULT_TERMS)
    target_format_suggested = False
    if not targets and len(unknown) == 1:
        format_name = next(iter(unknown))
        (targets if creates_result else sources).add(format_name)
        unknown.clear()
    if not targets and creates_result:
        defaults = {
            format_name
            for format_name, terms in _DEFAULT_FORMAT_TERMS.items()
            if any(term in user_text.casefold() for term in terms)
        }
        if len(defaults) == 1:
            targets = defaults
            target_format_suggested = True
    if len(targets) > 1 or len(unknown) > 1:
        return OfficeSkillRoute(
            "office-documents",
            None,
            conflict=True,
            clarification_question=FORMAT_CLARIFICATION_QUESTION,
        )
    if unknown:
        sources |= unknown
    target_format = next(iter(targets), None)
    format_name = target_format
    if format_name is None and len(sources) == 1:
        format_name = next(iter(sources))
    if format_name is not None:
        return OfficeSkillRoute(
            FORMAT_SKILLS[format_name],
            format_name,
            tuple(sorted(sources)),
            target_format,
            target_format_suggested,
        )
    if sources:
        return OfficeSkillRoute(
            "office-documents",
            None,
            tuple(sorted(sources)),
        )
    lowered = user_text.casefold()
    if any(term in lowered for term in _GENERAL_TERMS):
        return OfficeSkillRoute("office-work-os", None)
    return None


__all__ = [
    "FORMAT_SKILLS",
    "FORMAT_CLARIFICATION_QUESTION",
    "OfficeSkillRoute",
    "route_office_request",
]
