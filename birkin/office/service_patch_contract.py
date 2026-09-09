"""Format-aware validation shared by patch planning and execution."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

from .adapters.catalog import supported_formats
from .errors import DocumentError, DocumentErrorCode

_CELL_REFERENCE = re.compile(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*")
_FIELDS = {
    "docx": ({"field", "value"}, {"locator", "value"}),
    "hwpx": ({"field", "value"},),
    "xlsx": ({"cell", "value"}, {"locator", "value"}),
    "pptx": ({"placeholder_idx", "value"}, {"locator", "value"}),
}


def _invalid(message: str) -> DocumentError:
    return DocumentError(DocumentErrorCode.INVALID_INPUT, "plan", message)


def _string(operation: Mapping[str, object], key: str) -> str:
    value = operation.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"patch operation {key!r} must be a non-empty string")
    return value


def _validate_value(format_name: str, operation: Mapping[str, object]) -> None:
    value = operation.get("value")
    if format_name == "docx" and "locator" in operation:
        locator = operation.get("locator")
        if not isinstance(locator, Mapping) or set(locator) != {"format", "index"}:
            raise _invalid("DOCX paragraph locator requires format and index")
        index = locator.get("index")
        if locator.get("format") != "docx" or isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise _invalid("DOCX paragraph locator requires format docx and a positive index")
        if not isinstance(value, str):
            raise _invalid("DOCX paragraph patch value must be a string")
    elif format_name in {"docx", "hwpx"}:
        _ = _string(operation, "field")
        if not isinstance(value, str):
            raise _invalid("field patch value must be a string")
    elif format_name == "xlsx":
        locator = operation.get("locator")
        if locator is not None:
            if not isinstance(locator, Mapping) or set(locator) != {"sheet", "cell"}:
                raise _invalid("XLSX locator requires sheet and cell")
            if not isinstance(locator.get("sheet"), str) or not locator["sheet"]:
                raise _invalid("XLSX locator sheet must be a non-empty string")
            cell_value = locator.get("cell")
            if not isinstance(cell_value, str):
                raise _invalid("XLSX locator cell must be a string")
            cell = cell_value
        else:
            cell = _string(operation, "cell")
        if _CELL_REFERENCE.fullmatch(cell) is None:
            raise _invalid("patch operation 'cell' must be an XLSX cell reference")
        if isinstance(value, bool) or not (
            isinstance(value, int)
            or isinstance(value, float) and math.isfinite(value)
        ):
            raise _invalid("XLSX patch value must be a finite number")
    elif format_name == "pptx":
        locator = operation.get("locator")
        if locator is not None:
            if not isinstance(locator, Mapping) or set(locator) != {"slide_part", "placeholder_idx"}:
                raise _invalid("PPTX locator requires slide_part and placeholder_idx")
            slide_part = locator.get("slide_part")
            if not isinstance(slide_part, str) or re.fullmatch(r"ppt/slides/slide[1-9][0-9]*\.xml", slide_part) is None:
                raise _invalid("PPTX slide_part must name a slide XML part")
            index = locator.get("placeholder_idx")
        else:
            index = operation.get("placeholder_idx")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise _invalid("patch operation 'placeholder_idx' must be non-negative")
        if not isinstance(value, str):
            raise _invalid("placeholder patch value must be a string")


def validate_operations(
    format_name: str,
    operations: Sequence[Mapping[str, object]],
    *,
    operation_name: str,
    require_single: bool,
) -> None:
    """Reject unsupported formats and operation shapes before planning a write."""
    if format_name not in supported_formats(operation_name):
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "plan",
            f"{format_name} {operation_name} is unsupported",
            details={"format": format_name, "operation": operation_name},
        )
    if require_single and len(operations) != 1:
        raise _invalid("one narrow Wave 1 operation is required")
    if operation_name == "patch" and not operations:
        raise _invalid("at least one patch operation is required")
    if len(operations) > 1_000:
        raise _invalid("patch operations exceed the 1000 item limit")
    expected_shapes = _FIELDS.get(format_name)
    if expected_shapes is None:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "plan",
            f"{format_name} {operation_name} has no registered operation shape",
            details={"format": format_name, "operation": operation_name},
        )
    for operation in operations:
        if set(operation) not in expected_shapes:
            choices = [sorted(shape) for shape in expected_shapes]
            raise _invalid(
                f"{format_name} patch operation requires one of {choices}"
            )
        _validate_value(format_name, operation)
    targets = [
        tuple(sorted((key, repr(value)) for key, value in operation.items() if key != "value"))
        for operation in operations
    ]
    if len(set(targets)) != len(targets):
        raise _invalid("patch operations must target distinct locations")
