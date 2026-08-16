"""Managed workspace output-name validation."""

from __future__ import annotations

import unicodedata
from pathlib import Path

from .errors import DocumentError, DocumentErrorCode


def validate_output_name(output_name: object, suffix: str) -> str:
    if (
        not isinstance(output_name, str)
        or not output_name
        or output_name != unicodedata.normalize("NFC", output_name)
        or output_name in {".", ".."}
        or "/" in output_name
        or "\\" in output_name
        or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs"}
            for character in output_name
        )
        or Path(output_name).name != output_name
    ):
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "emit",
            "output_name must be one NFC logical file name",
        )
    if Path(output_name).suffix.lower() != suffix.lower():
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "emit",
            f"output_name must end with {suffix}",
        )
    return output_name
