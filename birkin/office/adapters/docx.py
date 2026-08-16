"""Lossless-surgical DOCX inspection and bounded operation adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import final

from ..errors import DocumentError, DocumentErrorCode
from ..package import preflight_package
from .docx_fields import merge_template as merge_docx_template
from .docx_fields import patch_field as patch_docx_field
from .docx_fragments import inventory_part
from .docx_nodes import DocxLocator, DocxNode, inventory_nodes, story_parts
from .docx_operations import patch_text as patch_docx_text
from .docx_operations import read_node as read_docx_node
from .docx_operations import refuse, tracked_change_refusal
from .docx_types import (
    DocxInspection,
    Inventory,
    IssueRecord,
    StructureRecord,
    empty_inventory,
)
from .ooxml_surgery import package_parts


@final
class DocxAdapter:
    format: str = "docx"

    def part_hashes(self, path: Path) -> dict[str, str]:
        return {
            name: metadata["original_sha256"]
            for name, metadata in preflight_package(path)["parts"].items()
        }

    def inspect(self, path: Path) -> DocxInspection:
        parts, digest = package_parts(path, None)
        body = parts.get("word/document.xml")
        if body is None:
            raise DocumentError(
                DocumentErrorCode.PACKAGE_INVALID,
                "inspect",
                "DOCX main document part is missing",
            )
        inventory: Inventory = empty_inventory()
        for name in story_parts(parts):
            found = inventory_part(name, parts[name])
            inventory["comment_ranges"].extend(found["comment_ranges"])
            inventory["bookmarks"].extend(found["bookmarks"])
            inventory["fields"].extend(found["fields"])
            inventory["tracked_changes"].extend(found["tracked_changes"])
            inventory["content_controls"].extend(found["content_controls"])
            inventory["boundaries"].extend(found["boundaries"])
        self._annotate_comment_definitions(parts, inventory["comment_ranges"])
        nodes = inventory_nodes(parts, digest)
        structures = [
            item
            for kind in (
                "content_controls",
                "fields",
                "tracked_changes",
                "comment_ranges",
                "bookmarks",
            )
            for item in inventory[kind]
        ]
        issues: list[IssueRecord] = [
            {
                "stable_id": item["stable_id"],
                "state": item["state"],
                "reasons": item["reasons"],
            }
            for item in structures
            if item["state"] != "valid"
        ]
        return {
            "source_sha256": digest,
            "paragraphs": self._nodes(nodes, "paragraph"),
            "runs": self._nodes(nodes, "run"),
            "tables": self._nodes(nodes, "table"),
            "headers": sorted(name for name in parts if re.fullmatch(r"word/header\d+\.xml", name)),
            "footers": sorted(name for name in parts if re.fullmatch(r"word/footer\d+\.xml", name)),
            "footnotes": [name for name in parts if name == "word/footnotes.xml"],
            "endnotes": [name for name in parts if name == "word/endnotes.xml"],
            "comments": [name for name in parts if name == "word/comments.xml"],
            "styles": [name for name in parts if name == "word/styles.xml"],
            "sections": len(re.findall(rb"<w:sectPr\b", body)),
            **inventory,
            "structures": structures,
            "issues": issues,
        }

    @staticmethod
    def _nodes(nodes: list[DocxNode], kind: str) -> list[DocxNode]:
        return [node for node in nodes if node["kind"] == kind]

    @staticmethod
    def _annotate_comment_definitions(
        parts: dict[str, bytes], ranges: list[StructureRecord]
    ) -> None:
        comments = parts.get("word/comments.xml", b"")
        raw_definitions: list[bytes] = re.findall(
            rb"<w:comment\b[^>]*\bw:id\s*=\s*['\"]([^'\"]+)['\"]",
            comments,
        )
        definitions = [
            value.decode("utf-8", errors="replace") for value in raw_definitions
        ]
        for item in ranges:
            native_id = item["id"]
            count = definitions.count(native_id) if native_id is not None else 0
            if count == 1:
                continue
            reason = "missing_comment_definition" if count == 0 else "duplicate_comment_definition"
            item["state"] = "malformed"
            item["reasons"] = sorted(set(item["reasons"] + [reason]))

    def read(
        self,
        source: Path,
        locator: DocxLocator,
        *,
        expected_source_sha256: str | None = None,
    ) -> DocxNode:
        return read_docx_node(
            source, locator, expected_source_sha256=expected_source_sha256
        )

    def patch_text(
        self,
        source: Path,
        output: Path,
        locator: DocxLocator,
        value: str,
        *,
        expected_text: str | None = None,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        return patch_docx_text(
            source,
            output,
            locator,
            value,
            expected_text=expected_text,
            expected_source_sha256=expected_source_sha256,
        )

    def patch_field(
        self,
        source: Path,
        output: Path,
        key: str,
        value: str,
        *,
        expected_text: str | None = None,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        return patch_docx_field(
            source,
            output,
            key,
            value,
            expected_text=expected_text,
            expected_source_sha256=expected_source_sha256,
        )

    def merge_template(
        self,
        template: Path,
        output: Path,
        merge_map: Mapping[str, object],
        *,
        expected_template_sha256: str | None = None,
    ) -> dict[str, object]:
        return merge_docx_template(
            template,
            output,
            merge_map,
            expected_template_sha256=expected_template_sha256,
        )

    read_node = read
    edit_text = patch_text
    patch_content_control = patch_field
    patch_simple_field = patch_field
    fill_template = merge_template

    def patch_tracked_change(
        self,
        _source: Path,
        _output: Path,
        _change_id: str | None = None,
        *,
        action: str,
        **_metadata: object,
    ) -> None:
        tracked_change_refusal(action)

    def create_tracked_change(self, *_args: object, **_kwargs: object) -> None:
        tracked_change_refusal("create")

    def accept_tracked_change(self, *_args: object, **_kwargs: object) -> None:
        tracked_change_refusal("accept")

    def reject_tracked_change(self, *_args: object, **_kwargs: object) -> None:
        tracked_change_refusal("reject")

    def patch_table(self, *_args: object, **_kwargs: object) -> None:
        refuse("edit_table", "table and nested-table structural edits are unsupported")

    def patch_bookmark(self, *_args: object, **_kwargs: object) -> None:
        refuse("edit_bookmark", "bookmark range mutation is unsupported")

    def patch_comment_range(self, *_args: object, **_kwargs: object) -> None:
        refuse("edit_comment_range", "comment range mutation is unsupported")

    def patch_complex_field(self, *_args: object, **_kwargs: object) -> None:
        refuse("edit_complex_field", "complex field mutation is unsupported")

    def patch_style(self, *_args: object, **_kwargs: object) -> None:
        refuse("edit_style", "style definition mutation is unsupported")
