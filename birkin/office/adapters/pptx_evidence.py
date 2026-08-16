from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from ..errors import DocumentError, DocumentErrorCode
from .ooxml_surgery import package_parts
from .pptx_types import OperationEvidence, PreservationRecord

_RELATIONSHIP = ".rels"
_CATEGORIES: dict[str, tuple[str, ...]] = {
    "masters_preserved": ("ppt/slideMasters/",),
    "layouts_preserved": ("ppt/slideLayouts/",),
    "themes_preserved": ("ppt/theme/",),
    "notes_preserved": ("ppt/notesSlides/",),
    "media_preserved": ("ppt/media/",),
}


def hashes(parts: Mapping[str, bytes]) -> dict[str, str]:
    return {
        name: hashlib.sha256(payload).hexdigest() for name, payload in parts.items()
    }


def _category_preserved(
    before: Mapping[str, str], after: Mapping[str, str], prefixes: tuple[str, ...]
) -> bool:
    selected = {name for name in before if name.startswith(prefixes)}
    return selected == {name for name in after if name.startswith(prefixes)} and all(
        before[name] == after[name] for name in selected
    )


def verify_evidence(
    output: Path,
    source_digest: str,
    before_parts: Mapping[str, bytes],
    replacements: Mapping[str, bytes],
    operation: str,
) -> OperationEvidence:
    after_parts, _ = package_parts(output, None)
    before = hashes(before_parts)
    after = hashes(after_parts)
    expected_names = set(before_parts)
    if set(after_parts) != expected_names:
        raise DocumentError(
            DocumentErrorCode.VALIDATION_FAILED,
            "validate",
            "PPTX surgical write changed the package part set",
            details={"operation": operation},
        )
    changed = sorted(name for name in before if before[name] != after[name])
    intended = sorted(
        name
        for name, payload in replacements.items()
        if before.get(name) != hashlib.sha256(payload).hexdigest()
    )
    if changed != intended or any(after[name] != hashlib.sha256(replacements[name]).hexdigest() for name in intended):
        raise DocumentError(
            DocumentErrorCode.VALIDATION_FAILED,
            "validate",
            "PPTX surgical write changed an unintended part",
            details={"operation": operation, "expected": intended, "actual": changed},
        )
    relationships = [name for name in before if name.endswith(_RELATIONSHIP)]
    preservation: PreservationRecord = {
        "unchanged_parts": len(before) - len(changed),
        "unchanged_sha256_verified": True,
        "relationships_preserved": all(before[name] == after[name] for name in relationships),
        "masters_preserved": _category_preserved(before, after, _CATEGORIES["masters_preserved"]),
        "layouts_preserved": _category_preserved(before, after, _CATEGORIES["layouts_preserved"]),
        "themes_preserved": _category_preserved(before, after, _CATEGORIES["themes_preserved"]),
        "notes_preserved": _category_preserved(before, after, _CATEGORIES["notes_preserved"]),
        "media_preserved": _category_preserved(before, after, _CATEGORIES["media_preserved"]),
        "intentionally_changed": intended,
    }
    return {
        "operation": operation,
        "status": "applied",
        "source_sha256": source_digest,
        "changed_parts": changed,
        "before_sha256": {name: before[name] for name in changed},
        "after_sha256": {name: after[name] for name in changed},
        "preservation": preservation,
        "loss": {"state": "none", "items": []},
        "visual_verification": {"state": "not_run", "reason": "renderer_unavailable"},
    }


def refuse(operation: str, reason: str) -> None:
    raise DocumentError(
        DocumentErrorCode.LOSSY_WRITE_BLOCKED,
        "apply",
        f"lossless PPTX {operation} is not available",
        details={
            "operation": operation,
            "reason": reason,
            "status": "refused",
            "preservation": "source_not_modified",
            "loss": {"state": "blocked", "items": [reason]},
            "visual_verification": {"state": "not_run", "reason": "operation_refused"},
        },
    )
