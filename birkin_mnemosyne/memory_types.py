"""Typed dictionary contracts for the ergonomic vault memory surface."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict


class MemoryNote(TypedDict):
    """One note returned by :meth:`VaultMemory.list_notes`."""

    title: str
    type: str
    updated: str
    confidence: float
    polarity: str
    zone: str
    path: Path


class MemorySearchHit(TypedDict):
    """One compatibility search result returned by :class:`VaultMemory`."""

    title: str
    snippet: str
    zone: str
    related: list[str]
