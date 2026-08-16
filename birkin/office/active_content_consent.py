"""Exact preservation consent for inventoried active document content."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .active_content_inventory import (
    ActiveContentEvidence,
    InventoryItem,
    inspect_inventory,
)
from .errors import DocumentError, DocumentErrorCode

PRESERVATION_MODE = "preserve_exact"


def inspect_active_content(path: Path) -> ActiveContentEvidence:
    """Return a deterministic inventory without executing or resolving content."""
    return inspect_inventory(path, PRESERVATION_MODE)


def require_preservation_consent(
    evidence: ActiveContentEvidence, consent: object
) -> None:
    if not evidence["inventory"]:
        return
    if isinstance(consent, Mapping):
        raw = cast("Mapping[object, object]", consent)
        supplied = {key: value for key, value in raw.items() if isinstance(key, str)}
    else:
        supplied = {}
    if set(supplied) != {"source_sha256", "inventory_sha256", "preservation_mode"}:
        raise DocumentError(
            DocumentErrorCode.POLICY_DENIED,
            "preflight",
            "active content requires exact hash-bound preservation consent",
            details=dict(evidence),
        )
    if supplied.get("preservation_mode") != PRESERVATION_MODE:
        raise DocumentError(
            DocumentErrorCode.UNSUPPORTED_EDIT,
            "preflight",
            "only exact active-content preservation is supported",
            details={"supported_mode": PRESERVATION_MODE},
        )
    if supplied.get("source_sha256") != evidence["source_sha256"] or supplied.get(
        "inventory_sha256"
    ) != evidence["inventory_sha256"]:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "preflight",
            "active-content consent is stale or does not match this source",
            artifact_sha256=evidence["source_sha256"],
            details=dict(evidence),
        )


def verify_preserved(
    source: ActiveContentEvidence, output: Path
) -> ActiveContentEvidence:
    current = inspect_active_content(output)
    if current["inventory_sha256"] != source["inventory_sha256"]:
        raise DocumentError(
            DocumentErrorCode.POLICY_DENIED,
            "validate",
            "active content, signatures, encryption, or related relationships changed",
            details={
                "expected_inventory_sha256": source["inventory_sha256"],
                "actual_inventory_sha256": current["inventory_sha256"],
            },
        )
    return current


__all__ = [
    "PRESERVATION_MODE",
    "ActiveContentEvidence",
    "InventoryItem",
    "inspect_active_content",
    "require_preservation_consent",
    "verify_preserved",
]
