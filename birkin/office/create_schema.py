"""Machine-consumed JSON schema for typed document creation plans."""

from __future__ import annotations


def _closed(properties: dict[str, object], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def create_content_schema() -> dict[str, object]:
    text = {"type": "string", "maxLength": 100_000}
    paragraphs = _closed(
        {
            "paragraphs": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10_000,
                "items": text,
            }
        },
        ["paragraphs"],
    )
    rows = {
        "type": "array",
        "minItems": 1,
        "maxItems": 100_000,
        "items": {
            "type": "array",
            "maxItems": 16_384,
            "items": {"type": ["string", "number", "integer", "boolean", "null"]},
        },
    }
    sheet = _closed(
        {
            "name": {"type": "string", "minLength": 1, "maxLength": 31},
            "rows": rows,
        },
        ["name", "rows"],
    )
    workbook = _closed(
        {
            "sheets": {
                "type": "array",
                "minItems": 1,
                "maxItems": 256,
                "items": sheet,
            }
        },
        ["sheets"],
    )
    slide = _closed(
        {"title": text, "body": {"type": ["string", "null"], "maxLength": 100_000}},
        ["title"],
    )
    presentation = _closed(
        {
            "slides": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10_000,
                "items": slide,
            }
        },
        ["slides"],
    )
    rich_binding = _closed(
        {"value": text, "expected_text": {"type": ["string", "null"]}},
        ["value"],
    )
    hwpx = _closed(
        {
            "bindings": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 10_000,
                "additionalProperties": {"oneOf": [text, rich_binding]},
            },
            "allow_active_content": {"type": "boolean"},
            "allow_signatures": {"type": "boolean"},
            "allow_external_relationships": {"type": "boolean"},
        },
        ["bindings"],
    )
    return {
        "oneOf": [paragraphs, workbook, presentation, hwpx],
        "description": "Strict format-specific plan; HWPX uses a trusted template.",
    }
