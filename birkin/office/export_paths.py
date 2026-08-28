"""Authenticated export helper pathname derivation."""

from __future__ import annotations

from pathlib import Path


def staging_path(
    destination: Path,
    transaction_id: str,
    rollback_token: str,
) -> Path:
    return destination.parent / (
        f".birkin-export-{transaction_id}-{rollback_token}"
        f"{destination.suffix}"
    )


def valid_staging_paths(
    destination: Path,
    transaction_id: str,
    rollback_token: str,
) -> frozenset[Path]:
    legacy = destination.parent / (
        f".birkin-export-{transaction_id}{destination.suffix}"
    )
    return frozenset(
        {
            legacy,
            staging_path(destination, transaction_id, rollback_token),
        }
    )
