"""Typed XLSX locators, inventories, and surgical-edit receipts."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class SheetLocator(TypedDict):
    sheet: str
    sheet_id: NotRequired[str]
    part_uri: NotRequired[str]


class CellLocator(SheetLocator):
    cell: str


class RangeLocator(SheetLocator):
    range: str


class TableLocator(SheetLocator):
    table: str


class NamedRangeLocator(TypedDict):
    name: str
    scope: str | None


class ChartLocator(SheetLocator):
    relationship_id: str


InventoryRecord = dict[str, object]


class XlsxInventory(TypedDict):
    sheets: list[InventoryRecord]
    cells: list[InventoryRecord]
    ranges: list[InventoryRecord]
    tables: list[InventoryRecord]
    named_ranges: list[InventoryRecord]
    styles: list[InventoryRecord]
    comments: list[InventoryRecord]
    merged_cells: list[InventoryRecord]
    hidden_rows: list[InventoryRecord]
    hidden_columns: list[InventoryRecord]
    drawings: list[InventoryRecord]


class EditReceipt(TypedDict):
    operation: str
    locator: dict[str, str]
    changed_parts: list[str]
    preservation: Literal["untouched_parts_byte_identical"]
    recalculated: bool
    cache_stale: bool
