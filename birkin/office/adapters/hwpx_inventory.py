"""Serializable HWPX structural and metadata inventory."""

from __future__ import annotations

from ..package_types import PackageManifest
from .hwpx_model import decoded_text, scan_sections, section_names
from .hwpx_types import (
    CellRecord,
    FieldRecord,
    HwpxEncryptionInventory,
    HwpxInspection,
    ParagraphRecord,
    TableRecord,
)
from .hwpx_xml import attributes, elements


def _metadata_records(parts: dict[str, bytes], local_name: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for name, xml in parts.items():
        if name not in {"Contents/header.xml", "Contents/content.hpf"}:
            continue
        for span in elements(xml, local_name):
            record = attributes(xml, span)
            record["part"] = name
            records.append(record)
    ids = [record.get("id") for record in records]
    for record, native_id in zip(records, ids, strict=True):
        record["state"] = (
            "malformed"
            if not native_id
            else "duplicate"
            if ids.count(native_id) > 1
            else "valid"
        )
    return records


def inventory(
    parts: dict[str, bytes],
    digest: str,
    manifest: PackageManifest,
    encryption: HwpxEncryptionInventory,
) -> HwpxInspection:
    if encryption["encrypted"]:
        mime = manifest["parts"]["mimetype"]
        return {
            "source_sha256": digest,
            "sections": section_names(parts),
            "paragraphs": [],
            "paragraph_details": [],
            "fields": [],
            "field_details": [],
            "tables": [],
            "table_details": [],
            "cells": [],
            "cell_details": [],
            "fonts": [],
            "styles": [],
            "masters": [],
            "master_details": [],
            "headers": [],
            "footers": [],
            "metadata_parts": [name for name in ("Contents/content.hpf", "Contents/header.xml") if name in parts],
            "mimetype_first_stored": mime["index"] == 0 and mime["compress_type"] == 0,
            **encryption,
        }
    sections = scan_sections(parts)
    paragraph_details: list[ParagraphRecord] = []
    field_details: list[FieldRecord] = []
    table_details: list[TableRecord] = []
    cell_details: list[CellRecord] = []
    for section in sections:
        for item in section.paragraphs:
            paragraph_details.append(
                {
                    "locator": None
                    if item.paragraph_id is None
                    else {"part": item.part, "paragraph_id": item.paragraph_id},
                    "text": decoded_text(section.xml[item.span.start : item.span.end]),
                    "state": item.state,
                }
            )
        for item in section.fields:
            key = next((alias for alias in item.aliases if alias != item.field_id), item.field_id)
            field_details.append(
                {
                    "locator": None
                    if item.field_id is None
                    else {"part": item.part, "field_id": item.field_id},
                    "field_id": item.field_id,
                    "key": key,
                    "aliases": sorted(item.aliases),
                    "kind": item.kind,
                    "text": decoded_text(section.xml[item.start : item.end]),
                    "state": item.state,
                }
            )
        for item in section.tables:
            table_details.append(
                {
                    "locator": None
                    if item.table_id is None
                    else {"part": item.part, "table_id": item.table_id},
                    "table_id": item.table_id,
                    "state": item.state,
                }
            )
        for item in section.cells:
            locator = (
                None
                if item.table_id is None or item.row is None or item.column is None
                else {
                    "part": item.part,
                    "table_id": item.table_id,
                    "row": item.row,
                    "column": item.column,
                }
            )
            cell_details.append(
                {
                    "locator": locator,
                    "table_id": item.table_id,
                    "row": item.row,
                    "column": item.column,
                    "row_span": item.row_span,
                    "column_span": item.column_span,
                    "text": decoded_text(section.xml[item.span.start : item.span.end]),
                    "state": item.state,
                }
            )
    masters = sorted(
        name
        for name in parts
        if name.startswith("Contents/") and "master" in name.rsplit("/", 1)[-1].lower() and name.endswith(".xml")
    )
    headers = sorted(
        name
        for name in parts
        if "header" in name.rsplit("/", 1)[-1].lower() and name.endswith(".xml") and name != "Contents/header.xml"
    )
    footers = sorted(
        name for name in parts if "footer" in name.rsplit("/", 1)[-1].lower() and name.endswith(".xml")
    )
    for section in sections:
        local_names = {span.local_name for span in elements(section.xml)}
        if "header" in local_names:
            headers.append(section.part)
        if "footer" in local_names:
            footers.append(section.part)
    master_details: list[dict[str, object]] = []
    for name in masters:
        spans = elements(parts[name])
        local_names = {span.local_name for span in spans}
        has_header, has_footer = "header" in local_names, "footer" in local_names
        if has_header:
            headers.append(name)
        if has_footer:
            footers.append(name)
        root = spans[0] if spans else None
        master_details.append(
            {
                "part": name,
                "id": None if root is None else attributes(parts[name], root).get("id"),
                "sha256": manifest["parts"][name]["original_sha256"],
                "has_header": has_header,
                "has_footer": has_footer,
            }
        )
    mime = manifest["parts"]["mimetype"]
    return {
        "source_sha256": digest,
        "sections": section_names(parts),
        "paragraphs": paragraph_details,
        "paragraph_details": paragraph_details,
        "fields": field_details,
        "field_details": field_details,
        "tables": table_details,
        "table_details": table_details,
        "cells": cell_details,
        "cell_details": cell_details,
        "fonts": _metadata_records(parts, "font"),
        "styles": _metadata_records(parts, "style"),
        "masters": masters,
        "master_details": master_details,
        "headers": sorted(set(headers)),
        "footers": sorted(set(footers)),
        "metadata_parts": [name for name in ("Contents/content.hpf", "Contents/header.xml") if name in parts],
        "mimetype_first_stored": mime["index"] == 0 and mime["compress_type"] == 0,
        **encryption,
    }
