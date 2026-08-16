"""Typed template binding planner."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from .errors import DocumentError, DocumentErrorCode

TemplateField = Mapping[str, object]
TemplateOperation = dict[str, object]


def bind_template(
    fields: Sequence[TemplateField],
    bindings: Mapping[str, object],
    *,
    strict: bool = True,
    raw_token_fallback: bool = False,
) -> list[TemplateOperation]:
    operations: list[TemplateOperation] = []
    for key, value in bindings.items():
        candidates = [
            field
            for field in fields
            if field.get("key") == key
            and (field.get("kind") != "raw" or raw_token_fallback)
        ]
        native = [field for field in candidates if field.get("kind") != "raw"]
        candidates = native or candidates
        if len(candidates) != 1:
            if strict:
                raise DocumentError(
                    DocumentErrorCode.INVALID_INPUT,
                    "plan",
                    f"binding {key!r} is missing or ambiguous",
                )
            continue
        operations.append({**candidates[0], "value": value})
    return operations


def binding_values(bindings: object) -> dict[str, object]:
    """Validate public binding entries without silently collapsing duplicates."""
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT, "plan", "template bindings must be a list"
        )
    values: dict[str, object] = {}
    for raw in bindings:
        if not isinstance(raw, Mapping):
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "plan",
                "template binding must be an object",
            )
        binding = cast("Mapping[object, object]", raw)
        key = binding.get("key")
        if not isinstance(key, str) or not key:
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "plan",
                "template binding key must be a non-empty string",
            )
        if key in values:
            raise DocumentError(
                DocumentErrorCode.INVALID_INPUT,
                "plan",
                f"duplicate template binding: {key!r}",
            )
        values[key] = binding.get("value")
    if not values:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "plan",
            "template bindings must not be empty",
        )
    return values


def native_template_fields(
    format_name: str, summary: Mapping[str, object]
) -> list[TemplateField]:
    """Project inspected native field inventory into planner descriptors."""
    key = "structures" if format_name == "docx" else "fields"
    raw_items = summary.get(key)
    if not isinstance(raw_items, list):
        return []
    fields: list[TemplateField] = []
    for raw in cast("list[object]", raw_items):
        if not isinstance(raw, Mapping):
            continue
        item = cast("Mapping[str, object]", raw)
        if item.get("state") != "valid":
            continue
        if format_name == "docx":
            if item.get("type") not in {"content_control", "simple_field"}:
                continue
            target = item.get("id") or item.get("instruction")
        elif format_name == "hwpx":
            target = item.get("field_id") or item.get("key")
        else:
            continue
        if isinstance(target, str) and target:
            fields.append(
                {"key": target, "kind": "native", "field": target}
            )
    return fields


def bind_patch_operations(
    format_name: str,
    fields: Sequence[TemplateField],
    bindings: Mapping[str, object],
    *,
    strict: bool,
    raw_token_fallback: bool,
) -> list[TemplateOperation]:
    """Bind planner descriptors to the executable narrow patch shape."""
    bound = bind_template(
        fields,
        bindings,
        strict=strict,
        raw_token_fallback=raw_token_fallback,
    )
    operations: list[TemplateOperation] = []
    for item in bound:
        value = item.get("value")
        if format_name in {"docx", "hwpx"}:
            target = item.get("field") or item.get("field_id") or item.get("key")
            operation = {"field": target, "value": value}
        elif format_name == "xlsx":
            operation = {"cell": item.get("cell"), "value": value}
        elif format_name == "pptx":
            operation = {
                "placeholder_idx": item.get("placeholder_idx"),
                "value": value,
            }
        else:
            raise DocumentError(
                DocumentErrorCode.UNSUPPORTED_EDIT,
                "plan",
                f"{format_name} template fill is unsupported",
            )
        operations.append(operation)
    return operations
