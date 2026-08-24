"""Typed dictionary contracts for the mechanical memory index."""

from __future__ import annotations

from typing import TypeAlias, TypedDict


class NoteEntry(TypedDict):
    """One fully parsed note stored in the rebuildable index."""

    title: str
    rel: str
    zone: str
    type: str
    tags: list[str]
    links: list[str]
    created: str
    updated: str
    confidence: float
    polarity: str
    expires_at: str | None
    summary: str
    mtime: float
    size: int
    doclen: int
    terms: dict[str, int]


class NoteDynamics(TypedDict):
    """Persisted usage dynamics for one note."""

    strength: float
    stability: float
    access_count: int
    last_access: str


class ZoneDynamics(TypedDict):
    """Persisted access priority for one zone."""

    ema: float
    last_hit: str


class DynamicsState(TypedDict):
    """Complete persisted note and zone dynamics state."""

    notes: dict[str, NoteDynamics]
    zones: dict[str, ZoneDynamics]


class SearchHit(TypedDict):
    """One ranked index search result."""

    slug: str
    title: str
    zone: str
    rel: str
    type: str
    summary: str
    links: list[str]
    polarity: str
    score: float
    updated: str


class StaleNote(TypedDict):
    """One mechanically stale note candidate."""

    slug: str
    title: str
    zone: str
    last_access: str
    eff: float


class IndexStats(TypedDict):
    """Mechanical index statistics."""

    notes: int
    zones: int
    terms: int
    stale: int


ScanEntry: TypeAlias = tuple[str, float, int]
