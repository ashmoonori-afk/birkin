"""Lazy optional backends and writers for validated creation plans."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Final, Protocol, cast

from .create_content import (
    CellValue,
    ParagraphPlan,
    PresentationPlan,
    WorkbookPlan,
)
from .errors import DocumentError, DocumentErrorCode

_PACKAGES: Final[dict[str, tuple[str, str]]] = {
    "docx": ("python-docx", "uv sync --extra office"),
    "xlsx": ("openpyxl", "uv sync --extra office"),
    "pptx": ("python-pptx", "uv sync --extra office"),
}


class _Document(Protocol):
    def add_paragraph(self, text: str) -> object: ...
    def save(self, path: str) -> None: ...


class _Worksheet(Protocol):
    title: str
    def append(self, row: list[CellValue]) -> None: ...


class _Workbook(Protocol):
    active: _Worksheet
    def create_sheet(self) -> _Worksheet: ...
    def save(self, path: str) -> None: ...


class _TextShape(Protocol):
    text: str


class _ShapeCollection(Protocol):
    title: _TextShape


class _PlaceholderCollection(Protocol):
    def __getitem__(self, index: int) -> _TextShape: ...


class _Slide(Protocol):
    shapes: _ShapeCollection
    placeholders: _PlaceholderCollection


class _Slides(Protocol):
    def add_slide(self, layout: object) -> _Slide: ...


class _Presentation(Protocol):
    slide_layouts: Sequence[object]
    slides: _Slides
    def save(self, path: str) -> None: ...


def module_member(module: ModuleType, name: str) -> object:
    namespace: dict[str, object] = vars(module)
    return namespace[name]


def optional_backend(module_name: str, format_name: str) -> ModuleType:
    """Import an optional writer or raise a typed capability refusal."""
    package, install_hint = _PACKAGES[format_name]
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise DocumentError(
            DocumentErrorCode.CAPABILITY_UNAVAILABLE,
            "emit",
            f"{format_name} creation requires the {package} package",
            details={"format": format_name, "package": package, "install_hint": install_hint},
        ) from exc


def write_docx(plan: ParagraphPlan, target: Path) -> None:
    factory = cast("Callable[[], _Document]", module_member(optional_backend("docx", "docx"), "Document"))
    document = factory()
    for paragraph in plan.paragraphs:
        _ = document.add_paragraph(paragraph)
    document.save(str(target))


def write_xlsx(plan: WorkbookPlan, target: Path) -> None:
    factory = cast("Callable[[], _Workbook]", module_member(optional_backend("openpyxl", "xlsx"), "Workbook"))
    workbook = factory()
    first = workbook.active
    for index, sheet in enumerate(plan.sheets):
        worksheet = first if index == 0 else workbook.create_sheet()
        worksheet.title = sheet.name
        for row in sheet.rows:
            worksheet.append(list(row))
    workbook.save(str(target))


def write_pptx(plan: PresentationPlan, target: Path) -> None:
    factory = cast("Callable[[], _Presentation]", module_member(optional_backend("pptx", "pptx"), "Presentation"))
    presentation = factory()
    layout = presentation.slide_layouts[1]
    for item in plan.slides:
        slide = presentation.slides.add_slide(layout)
        slide.shapes.title.text = item.title
        slide.placeholders[1].text = "" if item.body is None else item.body
    presentation.save(str(target))
