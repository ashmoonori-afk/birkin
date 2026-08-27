"""Cryptographic identity for exact approved Office operations."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from .artifact_serialization import canonical_integrity_json


class ExportAuthority(Protocol):
    """Authority fields shared by approval and export requests."""

    @property
    def actor(self) -> str: ...

    @property
    def proposal_digest(self) -> str: ...

    @property
    def operations(self) -> Sequence[Mapping[str, object]]: ...

    @property
    def overwrite_approved(self) -> bool: ...


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


def authority_digest(
    destination: Path,
    source_sha256: str,
    request: ExportAuthority,
) -> str:
    """Bind every caller-controlled field that grants one exact export."""
    authority = {
        "destination": str(destination),
        "source_sha256": source_sha256,
        "actor": request.actor,
        "proposal_digest": request.proposal_digest,
        "operations": [dict(operation) for operation in request.operations],
        "overwrite_approved": request.overwrite_approved,
    }
    return hashlib.sha256(
        canonical_integrity_json(authority).encode("utf-8")
    ).hexdigest()
