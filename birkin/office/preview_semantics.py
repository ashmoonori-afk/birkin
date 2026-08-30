"""Human-readable semantic summaries for proven structured preview changes."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TypedDict, runtime_checkable

from .errors import DocumentError, DocumentErrorCode


@runtime_checkable
class _StructuredMapping(Protocol):
    def get(self, key: str, default: None = None) -> object | None: ...

    def items(self) -> Iterable[tuple[str, object]]: ...


class PreviewSummary(TypedDict):
    """One structured before-and-after description for a proposed operation."""

    location: str
    before: str
    after: str


@dataclass(frozen=True, slots=True)
class _SourceNode:
    locator: dict[str, str | int]
    kind: str
    text: str


def _precondition(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.PRECONDITION_FAILED, "preview", message)


def _mapping(value: _StructuredMapping) -> dict[str, object]:
    return dict(value.items())


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise _precondition(f"{label} must be a non-empty string")
    return value


def _locator(value: object, label: str) -> dict[str, str | int]:
    if not isinstance(value, _StructuredMapping):
        raise _precondition(f"{label} must be an object")
    raw = _mapping(value)
    locator: dict[str, str | int] = {}
    for key, item in raw.items():
        if isinstance(item, str) and item:
            locator[key] = item
        elif isinstance(item, int) and not isinstance(item, bool):
            locator[key] = item
        else:
            raise _precondition(f"{label} values must be non-empty strings or integers")
    if not locator:
        raise _precondition(f"{label} must not be empty")
    return locator


def _nodes(preview: Mapping[str, object]) -> list[_SourceNode]:
    container = preview
    embedded = preview.get("preview")
    if embedded is not None:
        if not isinstance(embedded, _StructuredMapping):
            raise _precondition("structured preview must be an object")
        container = _mapping(embedded)
    raw_nodes = container.get("nodes")
    if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, (str, bytes)):
        raise _precondition("structured preview nodes must be a list")
    nodes: list[_SourceNode] = []
    for raw_node in raw_nodes:
        if not isinstance(raw_node, _StructuredMapping):
            raise _precondition("structured preview node must be an object")
        node = _mapping(raw_node)
        nodes.append(
            _SourceNode(
                locator=_locator(node.get("source_locator"), "node source_locator"),
                kind=_text(node.get("kind"), "node kind"),
                text=_text(node.get("text"), "node text"),
            )
        )
    return nodes


def _after(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(value)
    raise _precondition("operation value must be a non-empty string or finite number")


def _operation_selector(operation: Mapping[str, object]) -> tuple[dict[str, str | int], str]:
    match dict(operation):
        case {"cell": cell, "value": value}:
            return {"cell": _text(cell, "operation cell")}, _after(value)
        case {"locator": locator, "value": value}:
            return _locator(locator, "operation locator"), _after(value)
        case _:
            raise _precondition("operation has no supported preview locator")


def _node_for(
    nodes: Sequence[_SourceNode], selector: Mapping[str, str | int]
) -> _SourceNode:
    matches = [
        node
        for node in nodes
        if all(node.locator.get(key) == value for key, value in selector.items())
    ]
    if len(matches) != 1:
        raise _precondition("operation must match exactly one structured preview node")
    return matches[0]


def _location(node: _SourceNode) -> str:
    cell = node.locator.get("cell")
    sheet = node.locator.get("sheet")
    if isinstance(cell, str) and cell:
        if isinstance(sheet, str) and sheet:
            return f"{sheet}!{cell}"
        return cell
    format_name = node.locator.get("format")
    index = node.locator.get("index")
    if isinstance(format_name, str) and format_name and isinstance(index, int):
        return f"{format_name} {node.kind} {index}"
    raise _precondition("matched preview node has no human-readable location")


def summarize_operations(
    preview: Mapping[str, object], operations: Sequence[Mapping[str, object]]
) -> list[PreviewSummary]:
    """Summarize operations only when their source nodes prove every value."""
    nodes = _nodes(preview)
    summaries: list[PreviewSummary] = []
    for operation in operations:
        selector, after = _operation_selector(operation)
        node = _node_for(nodes, selector)
        location = _location(node)
        summaries.append(
            {
                "location": location,
                "before": node.text,
                "after": after,
            }
        )
    return summaries
