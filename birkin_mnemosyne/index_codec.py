"""Typed decoding for persisted index and dynamics sidecars."""

from __future__ import annotations

from .dynamics import STABILITY_INIT
from .index_types import DynamicsState, NoteDynamics, NoteEntry, ZoneDynamics
from .json_types import JsonValue


def _string(value: JsonValue, default: str = "") -> str:
    return str(value) if value is not None else default


def _float(value: JsonValue, default: float) -> float:
    match value:
        case bool() | int() | float() | str():
            try:
                return float(value)
            except ValueError:
                return default
        case _:
            return default


def _integer(value: JsonValue, default: int) -> int:
    match value:
        case bool() | int() | float() | str():
            try:
                return int(value)
            except ValueError:
                return default
        case _:
            return default


def _strings(value: JsonValue) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _terms(value: JsonValue) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        term: _integer(count, 0)
        for term, count in value.items()
        if _integer(count, 0) > 0
    }


def decode_note_entry(raw: JsonValue) -> NoteEntry | None:
    """Decode one persisted note entry, rejecting a non-object cache value."""
    if not isinstance(raw, dict):
        return None
    return {
        "title": _string(raw.get("title")),
        "rel": _string(raw.get("rel")),
        "zone": _string(raw.get("zone")),
        "type": _string(raw.get("type"), "topic"),
        "tags": _strings(raw.get("tags")),
        "links": _strings(raw.get("links")),
        "created": _string(raw.get("created")),
        "updated": _string(raw.get("updated")),
        "confidence": _float(raw.get("confidence"), 0.5),
        "polarity": _string(raw.get("polarity"), "positive"),
        "expires_at": (
            _string(raw.get("expires_at")) if raw.get("expires_at") else None
        ),
        "summary": _string(raw.get("summary")),
        "mtime": _float(raw.get("mtime"), 0.0),
        "size": _integer(raw.get("size"), 0),
        "doclen": _integer(raw.get("doclen"), 0),
        "terms": _terms(raw.get("terms")),
    }


def decode_notes(raw: JsonValue) -> dict[str, NoteEntry]:
    """Decode the note map from a compatible persisted index."""
    if not isinstance(raw, dict):
        return {}
    notes: dict[str, NoteEntry] = {}
    for note_slug, value in raw.items():
        entry = decode_note_entry(value)
        if entry is not None:
            notes[note_slug] = entry
    return notes


def _note_dynamics(raw: JsonValue) -> NoteDynamics | None:
    if not isinstance(raw, dict):
        return None
    return {
        "strength": _float(raw.get("strength"), 1.0),
        "stability": _float(raw.get("stability"), STABILITY_INIT),
        "access_count": _integer(raw.get("access_count"), 0),
        "last_access": _string(raw.get("last_access")),
    }


def _zone_dynamics(raw: JsonValue) -> ZoneDynamics | None:
    if not isinstance(raw, dict):
        return None
    return {
        "ema": _float(raw.get("ema"), 0.0),
        "last_hit": _string(raw.get("last_hit")),
    }


def decode_dynamics(raw: JsonValue) -> DynamicsState:
    """Decode dynamics state, dropping malformed nested records."""
    state: DynamicsState = {"notes": {}, "zones": {}}
    if not isinstance(raw, dict):
        return state
    raw_notes = raw.get("notes")
    if isinstance(raw_notes, dict):
        for note_slug, value in raw_notes.items():
            dynamics = _note_dynamics(value)
            if dynamics is not None:
                state["notes"][note_slug] = dynamics
    raw_zones = raw.get("zones")
    if isinstance(raw_zones, dict):
        for zone, value in raw_zones.items():
            dynamics = _zone_dynamics(value)
            if dynamics is not None:
                state["zones"][zone] = dynamics
    return state
