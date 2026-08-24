"""Cryptographic identity for exact approved Office operations."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from .artifact_serialization import canonical_integrity_json


def proposal_digest(
    operations: Sequence[Mapping[str, object]],
    source_sha256: str,
    outcome: str,
) -> str:
    """Bind exact operation data, source bytes, and declared outcome."""
    proposal = {
        "operations": [dict(operation) for operation in operations],
        "source_sha256": source_sha256,
        "outcome": outcome,
    }
    return hashlib.sha256(
        canonical_integrity_json(proposal).encode("utf-8")
    ).hexdigest()
