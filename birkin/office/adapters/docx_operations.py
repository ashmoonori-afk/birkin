"""Bounded DOCX node reads/text edits and truthful structural refusals."""

from __future__ import annotations

import re
from pathlib import Path

from ..errors import DocumentError, DocumentErrorCode
from ..package import clone_package
from .docx_edit_guard import validate_edit_fragment, word_edit_context
from .docx_nodes import DocxLocator, DocxNode, resolve_node
from .ooxml_surgery import package_parts, splice_fragmented_text


def read_node(
    source: Path,
    locator: DocxLocator,
    *,
    expected_source_sha256: str | None = None,
) -> DocxNode:
    parts, digest = package_parts(source, expected_source_sha256)
    node, _start, _end, _block = resolve_node(parts, digest, locator)
    return node


def patch_text(
    source: Path,
    output: Path,
    locator: DocxLocator,
    value: str,
    *,
    expected_text: str | None = None,
    expected_source_sha256: str | None = None,
) -> dict[str, object]:
    parts, digest = package_parts(source, expected_source_sha256)
    node, start, end, block = resolve_node(parts, digest, locator)
    kind = node["kind"]
    if kind == "table":
        refuse("edit_table", "table and nested-table text edits are unsupported")
    context = word_edit_context(parts[node["part"]], start)
    if "tbl" in context or node["table_depth"] > 0 or re.search(rb"<w:tbl\b", block):
        refuse("edit_text", "table-contained DOCX text edits are unsupported")
    if node.get("parent_type") in {"footnote", "endnote"} and node.get("parent_id") in {
        None,
        "-1",
        "0",
    }:
        refuse("edit_text", "separator note stories are read-only")
    if context & {"ins", "del", "moveFrom", "moveTo"} or re.search(
        rb"<w:(?:ins|del|moveFrom|moveTo)\b", block
    ):
        refuse("edit_text", "tracked or move revision text is read-only")
    if re.search(rb"<w:(?:fldSimple|fldChar|instrText|sdt)\b", block):
        refuse("edit_text", "field and content-control text requires its typed operation")
    validate_edit_fragment(block)
    changed, previous = splice_fragmented_text(
        parts[node["part"]], start, end, value, expected_text=expected_text
    )
    _ = clone_package(source, output, {node["part"]: changed})
    return {
        "source_part": node["part"],
        "source_sha256": digest,
        "locator": dict(locator),
        "previous_text": previous,
        "target_type": kind,
        "calculated": False,
    }


def refuse(operation: str, reason: str) -> None:
    raise DocumentError(
        DocumentErrorCode.UNSUPPORTED_EDIT,
        "apply",
        reason,
        details={"operation": operation, "bounded": True},
    )


def tracked_change_refusal(action: object) -> None:
    if action not in {"create", "accept", "reject"}:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "plan",
            "tracked-change action must be create, accept, or reject",
            details={"operation": "tracked_change"},
        )
    refuse(
        f"tracked_change_{action}",
        f"tracked-change {action} is unavailable because full range, part, author, time, ID, and move semantics are not proven",
    )
