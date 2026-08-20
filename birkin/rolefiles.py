"""Canonical on-disk role-profile file model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

PROFILE_ORDER: tuple[str, ...] = (
    "mask",
    "user",
    "preferences",
    "workflow",
    "automation",
)
DEFAULT_PROFILE_LIMITS: Mapping[str, int] = {
    "mask": 800,
    "user": 1375,
    "preferences": 1375,
    "workflow": 1000,
    "automation": 800,
}


@dataclass(frozen=True)
class ProfileDocument:
    """One role-profile document as stored under ``<home>/profile``."""

    name: str
    guidance: str
    entries: tuple[str, ...]
    used: int
    limit: int
    revision: str


@dataclass(frozen=True)
class ProfileSnapshot:
    """Consistent snapshot of all role-profile documents."""

    documents: Mapping[str, ProfileDocument]
    revision: str


@dataclass(frozen=True)
class ProfileEdit:
    """One transactional edit to a role-profile document."""

    target: str
    action: Literal["add", "replace", "remove"]
    old_text: str = ""
    content: str = ""


class ProfileStore:
    """Read and write canonical role-profile files under one home directory."""

    def __init__(self, home: Path, limits: Mapping[str, int]) -> None:
        """Bind the store to ``home`` using the supplied per-document limits."""
        raise NotImplementedError

    def bootstrap(self) -> None:
        """Create any missing profile files without changing existing content."""
        raise NotImplementedError

    def snapshot(self) -> ProfileSnapshot:
        """Return a lock-consistent snapshot of all profile documents."""
        raise NotImplementedError

    def apply(
        self,
        edit: ProfileEdit,
        *,
        expected_revision: str | None = None,
    ) -> ProfileSnapshot:
        """Apply one edit atomically and return the resulting snapshot."""
        raise NotImplementedError

    def apply_batch(
        self,
        edits: Sequence[ProfileEdit],
        *,
        expected_revision: str | None = None,
    ) -> ProfileSnapshot:
        """Apply a batch of edits as one optimistic transaction."""
        raise NotImplementedError
