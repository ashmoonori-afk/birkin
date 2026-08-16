"""Stable locator and binding types for bounded HWPX operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypedDict


@dataclass(frozen=True, slots=True)
class SectionLocator:
    part: str


@dataclass(frozen=True, slots=True)
class ParagraphLocator:
    part: str
    paragraph_id: str


@dataclass(frozen=True, slots=True)
class TextLocator:
    part: str
    paragraph_id: str
    run_index: int
    text_index: int = 0


@dataclass(frozen=True, slots=True)
class TableLocator:
    part: str
    table_id: str


@dataclass(frozen=True, slots=True)
class CellLocator:
    part: str
    table_id: str
    row: int
    column: int


@dataclass(frozen=True, slots=True)
class FieldLocator:
    part: str
    field_id: str


class FieldBinding(TypedDict):
    value: str
    expected_text: str | None


class ParagraphRecord(TypedDict):
    locator: Mapping[str, object] | None
    text: str
    state: str


class FieldRecord(TypedDict):
    locator: Mapping[str, object] | None
    field_id: str | None
    key: str | None
    aliases: list[str]
    kind: str
    text: str
    state: str


class TableRecord(TypedDict):
    locator: Mapping[str, object] | None
    table_id: str | None
    state: str


class CellRecord(TypedDict):
    locator: Mapping[str, object] | None
    table_id: str | None
    row: int | None
    column: int | None
    row_span: int
    column_span: int
    text: str
    state: str


class HwpxEncryptedPart(TypedDict):
    part: str
    media_type: str | None
    original_size: int | None
    source_sha256: str | None
    algorithm: str | None
    initialisation_vector: str | None
    key_derivation: str | None
    key_size: int | None
    iteration_count: int | None
    salt: str | None
    start_key_generation: str | None
    start_key_size: int | None
    checksum_type: str | None
    checksum: str | None
    declaration_state: Literal["valid", "malformed"]
    issues: list[str]


class HwpxEncryptionInventory(TypedDict):
    encrypted: bool
    password_required: bool
    credential_state: Literal["not_required", "required_not_supplied"]
    encryption_state: Literal["not_encrypted", "unsupported_encryption_state"]
    encryption_declaration_state: Literal["absent", "valid", "malformed"]
    encryption_manifest_part: str | None
    encryption_manifest_sha256: str | None
    encrypted_parts: list[HwpxEncryptedPart]
    encryption_issues: list[str]


class HwpxInspection(HwpxEncryptionInventory):
    source_sha256: str
    sections: list[str]
    paragraphs: list[ParagraphRecord]
    paragraph_details: list[ParagraphRecord]
    fields: list[FieldRecord]
    field_details: list[FieldRecord]
    tables: list[TableRecord]
    table_details: list[TableRecord]
    cells: list[CellRecord]
    cell_details: list[CellRecord]
    fonts: list[dict[str, str]]
    styles: list[dict[str, str]]
    masters: list[str]
    master_details: list[dict[str, object]]
    headers: list[str]
    footers: list[str]
    metadata_parts: list[str]
    mimetype_first_stored: bool
