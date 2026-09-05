"""Lazy optional backends and writers for validated creation plans."""

from __future__ import annotations

import importlib
import importlib.metadata
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
    "hwpx": ("python-hwpx", "uv sync --extra office"),
    "xlsx": ("openpyxl", "uv sync --extra office"),
    "pptx": ("python-pptx", "uv sync --extra office"),
    "pdf": ("reportlab", "uv sync --extra office-advanced"),
}
_EXACT_VERSIONS: Final[dict[str, str]] = {"hwpx": "6.1.0", "pdf": "4.5.1"}


class _Document(Protocol):
    def add_paragraph(self, text: str, style: str | None = None) -> object: ...
    def add_heading(self, text: str, level: int) -> object: ...
    def add_table(self, rows: int, cols: int) -> _Table: ...
    def save(self, path: str) -> None: ...


class _Cell(Protocol):
    text: str


class _Table(Protocol):
    def cell(self, row_idx: int, col_idx: int) -> _Cell: ...


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


class _ValidationReport(Protocol):
    ok: bool


class _HwpxDocument(Protocol):
    @classmethod
    def new(cls) -> _HwpxDocument: ...

    def add_paragraph(self, text: str) -> object: ...
    def save_to_path(self, path: Path) -> object: ...
    def validate(self) -> _ValidationReport: ...


def module_member(module: ModuleType, name: str) -> object:
    namespace: dict[str, object] = vars(module)
    return namespace[name]


def optional_backend(module_name: str, format_name: str) -> ModuleType:
    """Import an optional writer or raise a typed capability refusal."""
    package, install_hint = _PACKAGES[format_name]
    expected = _EXACT_VERSIONS.get(format_name)
    if expected is not None:
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise DocumentError(
                DocumentErrorCode.CAPABILITY_UNAVAILABLE,
                "emit",
                f"{format_name} creation requires {package}=={expected}",
                details={
                    "format": format_name,
                    "package": package,
                    "expected_version": expected,
                    "actual_version": None,
                    "install_hint": install_hint,
                },
            ) from exc
        if actual != expected:
            raise DocumentError(
                DocumentErrorCode.CAPABILITY_UNAVAILABLE,
                "emit",
                f"{format_name} creation requires {package}=={expected}",
                details={
                    "format": format_name,
                    "package": package,
                    "expected_version": expected,
                    "actual_version": actual,
                    "install_hint": install_hint,
                },
            )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise DocumentError(
            DocumentErrorCode.CAPABILITY_UNAVAILABLE,
            "emit",
            f"{format_name} creation requires the {package} package",
            details={"format": format_name, "package": package, "install_hint": install_hint},
        ) from exc
    return module


def write_docx(plan: ParagraphPlan, target: Path) -> None:
    factory = cast("Callable[[], _Document]", module_member(optional_backend("docx", "docx"), "Document"))
    document = factory()
    if plan.title is not None:
        _ = document.add_heading(plan.title, level=0)
    for paragraph in plan.paragraphs:
        _ = document.add_paragraph(paragraph)
    if plan.table:
        table = document.add_table(rows=len(plan.table), cols=len(plan.table[0]))
        for row_index, row in enumerate(plan.table):
            for column_index, value in enumerate(row):
                table.cell(row_index, column_index).text = value
    for item in plan.bullets:
        _ = document.add_paragraph(item, style="List Bullet")
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


def write_hwpx(plan: ParagraphPlan, target: Path) -> None:
    document_class = cast(
        "type[_HwpxDocument]",
        module_member(optional_backend("hwpx", "hwpx"), "HwpxDocument"),
    )
    document = document_class.new()
    for paragraph in plan.paragraphs:
        _ = document.add_paragraph(paragraph)
    _ = document.save_to_path(target)
    if not document.validate().ok:
        raise DocumentError(
            DocumentErrorCode.INTERNAL_ERROR,
            "validate",
            "python-hwpx emitted a document that failed validation",
        )
