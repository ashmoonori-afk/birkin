"""Format-aware validation shared by patch planning and execution."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

from .adapters.catalog import supported_formats
from .errors import DocumentError, DocumentErrorCode

_CELL_REFERENCE = re.compile(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*")
_FIELDS = {
    "docx": {"field", "value"},
    "hwpx": {"field", "value"},
    "xlsx": {"cell", "value"},
    "pptx": {"placeholder_idx", "value"},
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
    if format_name in {"docx", "hwpx"}:
        _ = _string(operation, "field")
        if not isinstance(value, str):
            raise _invalid("field patch value must be a string")
    elif format_name == "xlsx":
        cell = _string(operation, "cell")
        if _CELL_REFERENCE.fullmatch(cell) is None:
            raise _invalid("patch operation 'cell' must be an XLSX cell reference")
        if isinstance(value, bool) or not (
            isinstance(value, int)
            or isinstance(value, float) and math.isfinite(value)
        ):
            raise _invalid("XLSX patch value must be a finite number")
    elif format_name == "pptx":
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
    expected = _FIELDS.get(format_name)
    if expected is None:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "plan",
            f"{format_name} {operation_name} has no registered operation shape",
            details={"format": format_name, "operation": operation_name},
        )
    for operation in operations:
        if set(operation) != expected:
            raise _invalid(
                f"{format_name} patch operation requires exactly {sorted(expected)}"
            )
        _validate_value(format_name, operation)
