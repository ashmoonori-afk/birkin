from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from ..errors import DocumentError, DocumentErrorCode
from ..package import clone_package, preflight_package
from .ooxml_surgery import (
    attribute_equals,
    element_blocks,
    package_parts,
    require_one,
    splice_fragmented_text,
)
from .pptx_audit import audit_presentation
from .pptx_evidence import refuse, verify_evidence
from .pptx_inventory import presentation_inventory, shape_id
from .pptx_mutation import patch_shape_text, patch_table_cell, replace_image
from .pptx_structure import reorder_slides, set_slide_size
from .pptx_types import (
    OperationEvidence,
    PptxAudit,
    PresentationInventory,
    ShapeLocator,
    SlideLocator,
    TableCellLocator,
)


class PptxAdapter:
    format: str = "pptx"

    def inspect(self, path: Path) -> dict[str, object]:
        parts, _ = package_parts(path, None)
        audit = audit_presentation(parts)
        inventory = presentation_inventory(parts)
        return {
            **inventory,
            "slide_locators": inventory["slides"],
            "slides": sorted(name for name in parts if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            "layout_audit": audit,
            "warnings": audit["warnings"],
            "fonts": audit["fonts"],
            "media": audit["media"],
            "graph": audit["graph"],
            "visual_verification": audit["visual_verification"],
            "operation_contracts": self.operation_contracts(),
        }

    def inventory(self, path: Path) -> PresentationInventory:
        parts, _ = package_parts(path, None)
        return presentation_inventory(parts)

    def audit_layout(self, path: Path) -> PptxAudit:
        parts, _ = package_parts(path, None)
        return audit_presentation(parts)

    def part_hashes(self, path: Path) -> dict[str, str]:
        return {name: metadata["original_sha256"] for name, metadata in preflight_package(path)["parts"].items()}

    @staticmethod
    def operation_contracts() -> dict[str, dict[str, object]]:
        surgical = {"state": "lossless_surgical", "visual_verification": "not_run"}
        refused = {"state": "refused", "reason": "dependent_relationship_or_content_type_rewrite_required"}
        return {
            "placeholder_text": dict(surgical), "shape_text": dict(surgical),
            "table_cell": dict(surgical), "notes_text": dict(surgical),
            "embedded_image_same_encoding": dict(surgical), "slide_reorder": dict(surgical),
            "slide_size": dict(surgical), "slide_add": dict(refused),
            "slide_delete": dict(refused), "layout_change": dict(refused),
            "chart_data": dict(refused), "linked_media": dict(refused),
            "theme": dict(refused), "master": dict(refused),
        }

    def patch_placeholder(
        self,
        source: Path,
        output: Path,
        placeholder_idx: int,
        value: str,
        *,
        expected_text: str | None = None,
        slide_part: str = "ppt/slides/slide1.xml",
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        if isinstance(placeholder_idx, bool) or placeholder_idx < 0:
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "locate", "placeholder_idx must be non-negative")
        parts, digest = package_parts(source, expected_source_sha256)
        xml = parts.get(slide_part)
        if xml is None or re.fullmatch(r"ppt/slides/slide\d+\.xml", slide_part) is None:
            raise DocumentError(DocumentErrorCode.NODE_NOT_FOUND, "locate", "slide part not found")
        matches = [
            (slide_part, start, end, block)
            for start, end, block in element_blocks(xml, b"p:sp")
            if attribute_equals(block, b"p:ph", b"idx", str(placeholder_idx))
        ]
        _, start, end, block = require_one(matches, "PPTX placeholder index")
        changed, previous = splice_fragmented_text(xml, start, end, value, expected_text=expected_text)
        replacements = {slide_part: changed}
        _ = clone_package(source, output, replacements)
        try:
            evidence = verify_evidence(output, digest, parts, replacements, "placeholder_text_update")
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return {
            **evidence,
            "source_part": slide_part,
            "locator": {"part_uri": slide_part, "shape_id": shape_id(block), "placeholder_idx": str(placeholder_idx)},
            "previous_text": previous,
            "rendered": False,
        }

    def patch_text(
        self,
        source: Path,
        output: Path,
        locator: ShapeLocator,
        value: str,
        *,
        expected_text: str | None = None,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        evidence, previous = patch_shape_text(source, output, locator, value, expected_text=expected_text, expected_source_sha256=expected_source_sha256)
        return {**evidence, "locator": dict(locator), "previous_text": previous, "rendered": False}

    def update_text(self, source: Path, output: Path, locator: ShapeLocator, value: str, *, expected_text: str | None = None, expected_source_sha256: str | None = None) -> dict[str, object]:
        return self.patch_text(source, output, locator, value, expected_text=expected_text, expected_source_sha256=expected_source_sha256)

    def patch_notes(
        self,
        source: Path,
        output: Path,
        locator: ShapeLocator,
        value: str,
        *,
        expected_text: str | None = None,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        if not str(locator.get("part_uri", "")).startswith("ppt/notesSlides/"):
            raise DocumentError(DocumentErrorCode.INVALID_INPUT, "locate", "notes locator must target a notes slide part")
        evidence, previous = patch_shape_text(source, output, locator, value, expected_text=expected_text, expected_source_sha256=expected_source_sha256, operation="notes_text_update")
        return {**evidence, "locator": dict(locator), "previous_text": previous, "rendered": False}

    def update_notes(self, source: Path, output: Path, locator: ShapeLocator, value: str, *, expected_text: str | None = None, expected_source_sha256: str | None = None) -> dict[str, object]:
        return self.patch_notes(source, output, locator, value, expected_text=expected_text, expected_source_sha256=expected_source_sha256)

    def patch_table_cell(
        self,
        source: Path,
        output: Path,
        locator: TableCellLocator,
        value: str,
        *,
        expected_text: str | None = None,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        evidence, previous = patch_table_cell(source, output, locator, value, expected_text=expected_text, expected_source_sha256=expected_source_sha256)
        return {**evidence, "locator": dict(locator), "previous_text": previous, "rendered": False}

    def update_table_cell(self, source: Path, output: Path, locator: TableCellLocator, value: str, *, expected_text: str | None = None, expected_source_sha256: str | None = None) -> dict[str, object]:
        return self.patch_table_cell(source, output, locator, value, expected_text=expected_text, expected_source_sha256=expected_source_sha256)

    def replace_image(self, source: Path, output: Path, locator: ShapeLocator, image: bytes | Path, *, expected_media_sha256: str | None = None, expected_source_sha256: str | None = None) -> OperationEvidence:
        return replace_image(source, output, locator, image, expected_media_sha256=expected_media_sha256, expected_source_sha256=expected_source_sha256)

    def reorder_slides(self, source: Path, output: Path, order: Sequence[str | SlideLocator], *, expected_source_sha256: str | None = None) -> OperationEvidence:
        return reorder_slides(source, output, order, expected_source_sha256=expected_source_sha256)

    def reorder(self, source: Path, output: Path, order: Sequence[str | SlideLocator], *, expected_source_sha256: str | None = None) -> OperationEvidence:
        return self.reorder_slides(source, output, order, expected_source_sha256=expected_source_sha256)

    def set_slide_size(self, source: Path, output: Path, width_emu: int, height_emu: int, *, expected_source_sha256: str | None = None) -> OperationEvidence:
        return set_slide_size(source, output, width_emu, height_emu, expected_source_sha256=expected_source_sha256)

    def set_page_size(self, source: Path, output: Path, width_emu: int, height_emu: int, *, expected_source_sha256: str | None = None) -> OperationEvidence:
        return self.set_slide_size(source, output, width_emu, height_emu, expected_source_sha256=expected_source_sha256)

    def add_slide(self, *_args: object, **_kwargs: object) -> None:
        refuse("slide_add", "slide_relationship_content_type_and_layout_graph_rewrite_required")

    def delete_slide(self, *_args: object, **_kwargs: object) -> None:
        refuse("slide_delete", "notes_comments_sections_custom_shows_and_relationship_cleanup_required")

    def remove_slide(self, *_args: object, **_kwargs: object) -> None:
        self.delete_slide(*_args, **_kwargs)

    def change_layout(self, *_args: object, **_kwargs: object) -> None:
        refuse("layout_change", "placeholder_geometry_and_layout_relationship_rewrite_required")

    def set_slide_layout(self, *_args: object, **_kwargs: object) -> None:
        self.change_layout(*_args, **_kwargs)

    def update_layout(self, *_args: object, **_kwargs: object) -> None:
        self.change_layout(*_args, **_kwargs)

    def update_chart_data(self, *_args: object, **_kwargs: object) -> None:
        refuse("chart_data_update", "chart_cache_and_embedded_workbook_must_be_updated_atomically")

    def patch_chart(self, *_args: object, **_kwargs: object) -> None:
        self.update_chart_data(*_args, **_kwargs)

    def update_chart(self, *_args: object, **_kwargs: object) -> None:
        self.update_chart_data(*_args, **_kwargs)

    def replace_linked_media(self, *_args: object, **_kwargs: object) -> None:
        refuse("linked_media_replace", "external_target_cannot_be_hash_verified_offline")

    def replace_media(self, *_args: object, **_kwargs: object) -> None:
        refuse("media_replace", "audio_video_or_linked_media_requires_content_type_and_timing_validation")

    def update_theme(self, *_args: object, **_kwargs: object) -> None:
        refuse("theme_update", "master_layout_theme_cascade_cannot_be_visually_verified")

    def patch_theme(self, *_args: object, **_kwargs: object) -> None:
        self.update_theme(*_args, **_kwargs)

    def update_master(self, *_args: object, **_kwargs: object) -> None:
        refuse("master_update", "master_layout_placeholder_cascade_cannot_be_visually_verified")

    def patch_master(self, *_args: object, **_kwargs: object) -> None:
        self.update_master(*_args, **_kwargs)
