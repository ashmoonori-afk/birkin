"""Render a semantic Office diff into a preserved DOCX template."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from .create_backends import module_member, optional_backend
from .errors import DocumentError, DocumentErrorCode


class _Cell(Protocol):
    text: str


class _Row(Protocol):
    cells: Sequence[_Cell]


class _Table(Protocol):
    rows: Sequence[_Row]

    def add_row(self) -> _Row: ...


class _Document(Protocol):
    def add_heading(self, text: str, level: int) -> object: ...
    def add_table(self, rows: int, cols: int) -> _Table: ...
    def save(self, path: str) -> None: ...


def _invalid(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.INVALID_INPUT, "office_draft", message)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _nodes(value: object, label: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise _invalid(f"{label} must be a list")
    nodes: list[Mapping[str, object]] = []
    for item in cast("list[object]", value):
        node = _mapping(item, label)
        if not isinstance(node.get("order"), int) or not isinstance(node.get("kind"), str):
            raise _invalid(f"{label} contains an invalid structural node")
        if not isinstance(node.get("text"), str):
            raise _invalid(f"{label} contains a node without text")
        nodes.append(node)
    return nodes


def semantic_changes(diff: Mapping[str, object]) -> list[tuple[str, str, str]]:
    """Return changed semantic nodes in the stable order sealed by the diff."""
    semantic = _mapping(diff.get("semantic"), "Office semantic diff")
    normalized = _mapping(semantic.get("normalized_ir"), "Office normalized diff")
    left = _nodes(normalized.get("left"), "Office left diff")
    right = _nodes(normalized.get("right"), "Office right diff")
    changes: list[tuple[str, str, str]] = []
    for index in range(max(len(left), len(right))):
        old = left[index] if index < len(left) else None
        new = right[index] if index < len(right) else None
        if old == new:
            continue
        node = old or new
        assert node is not None
        label = f"{node['kind']} {node['order']}"
        old_value = "" if old is None else cast(str, old["text"])
        new_value = "" if new is None else cast(str, new["text"])
        changes.append((label, old_value, new_value))
    return changes


def render_comparison_report(
    template: Path,
    target: Path,
    diff: Mapping[str, object],
) -> None:
    """Preserve the template body and append one table row per semantic change."""
    factory = cast(
        "Callable[[str], _Document]",
        module_member(optional_backend("docx", "docx"), "Document"),
    )
    document = factory(str(template))
    _ = document.add_heading("Birkin comparison changes", level=1)
    table = document.add_table(rows=1, cols=3)
    for cell, value in zip(
        table.rows[0].cells,
        ("Field", "Old value", "New value"),
        strict=True,
    ):
        cell.text = value
    for label, old_value, new_value in semantic_changes(diff):
        row = table.add_row()
        for cell, value in zip(
            row.cells,
            (label, old_value, new_value),
            strict=True,
        ):
            cell.text = value
    document.save(str(target))
