"""Approved business-template inputs projected onto existing document plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import cast

from .create_content import invalid_content

_TEMPLATES: dict[str, dict[str, object]] = {
    "weekly_report": {
        "version": "1.0",
        "required": ("title", "period", "summary"),
        "paragraphs": ("period", "summary"),
        "list": "achievements",
        "table": "metrics",
    },
    "meeting_notes": {
        "version": "1.0",
        "required": ("title", "date", "summary"),
        "paragraphs": ("date", "summary"),
        "list": "decisions",
        "table": "actions",
    },
    "work_proposal": {
        "version": "1.0",
        "required": ("title", "problem", "proposal"),
        "paragraphs": ("problem", "proposal"),
        "list": "benefits",
        "table": "costs",
    },
}


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise invalid_content(f"{label} must be an object with string keys")
    return dict(cast("Mapping[str, object]", value))


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid_content(f"{label} must be a non-empty string")
    return value


def _text_list(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise invalid_content(f"{label} must be a list")
    return [_text(item, f"{label} item") for item in value]


def _table(value: object, label: str) -> list[list[str]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise invalid_content(f"{label} must be a list")
    rows: list[list[str]] = []
    width: int | None = None
    for raw_row in value:
        if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes)):
            raise invalid_content(f"{label} row must be a list")
        row = [_text(cell, f"{label} cell") for cell in raw_row]
        if not row or (width is not None and len(row) != width):
            raise invalid_content(f"{label} rows must be non-empty and have equal width")
        width = len(row)
        rows.append(row)
    return rows


def prepare_business_content(
    format_name: str, content: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Validate an approved template request and emit an existing backend plan."""
    raw_profile = content.get("business_template")
    if raw_profile is None:
        return dict(content), None
    if set(content) != {"business_template"}:
        raise invalid_content("business_template must be the only top-level content field")
    profile = _object(raw_profile, "business_template")
    unknown = sorted(set(profile) - {"name", "version", "values", "sources"})
    if unknown:
        raise invalid_content(f"business_template has unsupported keys: {unknown}")
    name = _text(profile.get("name"), "business_template name")
    definition = _TEMPLATES.get(name)
    if definition is None:
        raise invalid_content(f"unsupported business_template name: {name}")
    version = _text(profile.get("version"), "business_template version")
    if version != definition["version"]:
        raise invalid_content(f"unsupported {name} template version: {version}")
    values = _object(profile.get("values"), "business_template values")
    required = cast("tuple[str, ...]", definition["required"])
    missing = [key for key in required if not isinstance(values.get(key), str) or not str(values[key]).strip()]
    if missing:
        raise invalid_content(f"business_template is missing required values: {missing}")
    sources = _object(profile.get("sources", {}), "business_template sources")
    if any(key not in values or not isinstance(value, str) or not value.strip() for key, value in sources.items()):
        raise invalid_content("business_template sources must name supplied values and contain non-empty strings")
    paragraphs = [_text(values[key], f"business_template value {key}") for key in cast("tuple[str, ...]", definition["paragraphs"])]
    list_key = cast("str", definition["list"])
    table_key = cast("str", definition["table"])
    bullets = _text_list(values.get(list_key), f"business_template value {list_key}")
    table = _table(values.get(table_key), f"business_template value {table_key}")
    allowed = set(required) | {list_key, table_key}
    extra = sorted(set(values) - allowed)
    if extra:
        raise invalid_content(f"business_template values have unsupported keys: {extra}")
    digest = hashlib.sha256(
        json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=list).encode("utf-8")
    ).hexdigest()
    metadata = {
        "name": name,
        "version": version,
        "profile_sha256": digest,
        "required_fields": list(required),
        "missing_fields": [],
        "unreplaced_fields": [],
        "sources": sources,
        "layout_verified": False,
    }
    if format_name == "docx":
        return {
            "title": _text(values["title"], "business_template title"),
            "paragraphs": paragraphs,
            "list": bullets,
            "table": table,
        }, metadata
    if format_name == "hwpx":
        bindings = {key: value for key, value in values.items() if isinstance(value, str)}
        if bullets:
            bindings[list_key] = "\n".join(bullets)
        if table:
            bindings[table_key] = "\n".join("\t".join(row) for row in table)
        return {"bindings": bindings, "require_all_fields": True}, metadata
    raise invalid_content("business_template supports only DOCX and HWPX")


__all__ = ["prepare_business_content"]
