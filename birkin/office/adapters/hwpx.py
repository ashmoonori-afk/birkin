"""Safe package-native operations for XML-based HWPX documents."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from ..errors import DocumentError, DocumentErrorCode
from ..package import clone_package
from .hwpx_edit import (
    apply_edits,
    binding_values,
    cell_edit,
    field_edit,
    paragraph_edit,
    text_edit,
)
from .hwpx_encryption import inspect_encryption
from .hwpx_inventory import inventory
from .hwpx_model import scan_sections
from .hwpx_package import load_hwpx
from .hwpx_types import (
    CellLocator,
    FieldLocator,
    HwpxInspection,
    ParagraphLocator,
    TextLocator,
)


class HwpxAdapter:
    """Inspect and copy-on-write only structures with provable byte bounds."""

    format: str = "hwpx"

    def part_hashes(self, path: Path) -> dict[str, str]:
        _, _, manifest = load_hwpx(path)
        return {
            name: metadata["original_sha256"]
            for name, metadata in manifest["parts"].items()
        }

    def inspect(self, path: Path) -> HwpxInspection:
        parts, digest, manifest = load_hwpx(path, allow_encryption_inventory=True)
        return inventory(parts, digest, manifest, inspect_encryption(manifest))

    def decrypt(
        self, source: Path, _output: Path, *, password: str | None = None
    ) -> None:
        _ = password  # Credentials are not consumed without an approved decryptor.
        _ = load_hwpx(source)
        raise DocumentError(
            DocumentErrorCode.CAPABILITY_UNAVAILABLE,
            "decrypt",
            "HWPX decryption is unavailable",
            details={"reason": "unsupported_encryption_state"},
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
        parts, digest, _ = load_hwpx(source, expected_source_sha256)
        edit = field_edit(scan_sections(parts), key, value, expected_text)
        replacements, previous = apply_edits(parts, [edit])
        _ = clone_package(source, output, replacements)
        return {
            "source_part": edit.part,
            "source_sha256": digest,
            "previous_text": previous["field"],
            "field_id": edit.native_id,
            "field_kind": edit.kind,
            "rendered": False,
        }

    def patch_field_at(
        self,
        source: Path,
        output: Path,
        locator: FieldLocator,
        value: str,
        *,
        expected_text: str | None = None,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        parts, digest, _ = load_hwpx(source, expected_source_sha256)
        edit = field_edit(
            scan_sections(parts),
            locator.field_id,
            value,
            expected_text,
            part=locator.part,
            native_id_only=True,
        )
        replacements, previous = apply_edits(parts, [edit])
        _ = clone_package(source, output, replacements)
        return {
            "source_part": edit.part,
            "source_sha256": digest,
            "previous_text": previous["field"],
            "field_id": edit.native_id,
            "field_kind": edit.kind,
            "rendered": False,
        }

    def patch_paragraph_text(
        self,
        source: Path,
        output: Path,
        locator: ParagraphLocator,
        value: str,
        *,
        expected_text: str | None = None,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        parts, digest, _ = load_hwpx(source, expected_source_sha256)
        edit = paragraph_edit(scan_sections(parts), locator, value, expected_text)
        replacements, previous = apply_edits(parts, [edit])
        _ = clone_package(source, output, replacements)
        return {
            "source_part": edit.part,
            "source_sha256": digest,
            "previous_text": previous["paragraph"],
            "locator": {"part": locator.part, "paragraph_id": locator.paragraph_id},
            "rendered": False,
        }

    def patch_text(
        self,
        source: Path,
        output: Path,
        locator: TextLocator,
        value: str,
        *,
        expected_text: str | None = None,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        parts, digest, _ = load_hwpx(source, expected_source_sha256)
        edit = text_edit(scan_sections(parts), locator, value, expected_text)
        replacements, previous = apply_edits(parts, [edit])
        _ = clone_package(source, output, replacements)
        return {
            "source_part": edit.part,
            "source_sha256": digest,
            "previous_text": previous["text"],
            "locator": {
                "part": locator.part,
                "paragraph_id": locator.paragraph_id,
                "run_index": locator.run_index,
                "text_index": locator.text_index,
            },
            "rendered": False,
        }

    def patch_cell_text(
        self,
        source: Path,
        output: Path,
        locator: CellLocator,
        value: str,
        *,
        expected_text: str | None = None,
        expected_source_sha256: str | None = None,
    ) -> dict[str, object]:
        parts, digest, _ = load_hwpx(source, expected_source_sha256)
        edit = cell_edit(scan_sections(parts), locator, value, expected_text)
        replacements, previous = apply_edits(parts, [edit])
        _ = clone_package(source, output, replacements)
        return {
            "source_part": edit.part,
            "source_sha256": digest,
            "previous_text": previous["cell"],
            "locator": {
                "part": locator.part,
                "table_id": locator.table_id,
                "row": locator.row,
                "column": locator.column,
            },
            "rendered": False,
        }

    def derive_template(
        self,
        source: Path,
        output: Path,
        bindings: Mapping[object, object],
        *,
        expected_source_sha256: str,
    ) -> dict[str, object]:
        if not expected_source_sha256:
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "plan",
                "HWPX derivation requires a source SHA-256 precondition",
            )
        parts, digest, _ = load_hwpx(source, expected_source_sha256)
        models = scan_sections(parts)
        values = binding_values(bindings)
        edits = [
            field_edit(models, key, value, expected)
            for key, value, expected in values
        ]
        replacements, previous = apply_edits(parts, edits)
        _ = clone_package(source, output, replacements)
        return {
            "source_sha256": digest,
            "bindings": {
                key: edit.native_id
                for (key, _, _), edit in zip(values, edits, strict=True)
            },
            "previous_text": previous,
            "rendered": False,
        }

    patch_paragraph: Callable[..., dict[str, object]] = patch_paragraph_text
    patch_cell: Callable[..., dict[str, object]] = patch_cell_text
    @staticmethod
    def patch_section(*_args: object, **_kwargs: object) -> None:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "apply",
            "HWPX section insertion, deletion, and reordering are unsupported",
        )

    @staticmethod
    def patch_table_structure(*_args: object, **_kwargs: object) -> None:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "apply",
            "HWPX table geometry and span edits are unsupported",
        )

    patch_table: Callable[..., None] = patch_table_structure

    @staticmethod
    def patch_style_or_master(*_args: object, **_kwargs: object) -> None:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "apply",
            "HWPX style, font, header, footer, and master edits are unsupported",
        )

    patch_style: Callable[..., None] = patch_style_or_master
    patch_master: Callable[..., None] = patch_style_or_master
