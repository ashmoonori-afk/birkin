"""Frontmatter composition, expiry, and search snippet formatting."""

from __future__ import annotations

from collections import Counter
from datetime import date

from .index_types import NoteEntry
from .json_types import JsonObject, JsonValue


def compose_frontmatter(
    *,
    title: str,
    note_type: str,
    created: str,
    updated: str,
    confidence: float,
    sources: list[str],
    tags: list[str],
    expires_at: str | None = None,
    polarity: str = "positive",
    version: int = 1,
) -> str:
    """Compose the original stable note-frontmatter representation."""
    encoded_sources = ", ".join(f'"{source}"' for source in sources)
    encoded_tags = ", ".join(str(tag) for tag in tags)
    expiry_line = f"expires_at: {expires_at}\n" if expires_at else ""
    return "".join(
        [
            "---\n",
            f"title: {title}\n",
            f"type: {note_type}\n",
            f"created: {created}\n",
            f"updated: {updated}\n",
            f"confidence: {confidence}\n",
            f"polarity: {polarity}\n",
            f"version: {int(version)}\n",
            f"sources: [{encoded_sources}]\n",
            f"tags: [{encoded_tags}]\n",
            expiry_line,
            "---\n\n",
        ]
    )


def is_expired(metadata: JsonObject | NoteEntry) -> bool:
    """Return whether an optional expiry date is strictly in the past."""
    raw = metadata.get("expires_at")
    if not raw:
        return False
    try:
        return date.fromisoformat(str(raw)) < date.today()
    except ValueError:
        return False


def json_float(value: JsonValue, default: float) -> float:
    """Parse a numeric JSON scalar with a deterministic fallback."""
    match value:
        case bool() | int() | float() | str():
            try:
                return float(value)
            except ValueError:
                return default
        case _:
            return default


def json_int(value: JsonValue, default: int) -> int:
    """Parse an integer JSON scalar with a deterministic fallback."""
    match value:
        case bool() | int() | float() | str():
            try:
                return int(value)
            except ValueError:
                return default
        case _:
            return default


def snippet(text: str, terms: list[str] | str, width: int = 240) -> str:
    """Return the densest query-term window, earliest on score ties."""
    match terms:
        case str():
            query_terms = [terms]
        case list():
            query_terms = terms
    lowered = text.lower()
    hits: list[tuple[int, str]] = []
    for term in {term for term in query_terms if term}:
        start = 0
        while True:
            index = lowered.find(term, start)
            if index < 0:
                break
            hits.append((index, term))
            start = index + 1
    if not hits:
        return text.strip()[:width]
    hits.sort()
    in_window: Counter[str] = Counter()
    best_start = hits[0][0]
    best_end = best_start + len(hits[0][1])
    best_distinct = 1
    left = 0
    for position, term in hits:
        in_window[term] += 1
        while hits[left][0] < position - width:
            old_term = hits[left][1]
            in_window[old_term] -= 1
            if not in_window[old_term]:
                del in_window[old_term]
            left += 1
        if len(in_window) > best_distinct:
            best_distinct = len(in_window)
            best_start = hits[left][0]
            best_end = position + len(term)
    start = max(0, best_start - width // 8)
    end = max(best_start + width, best_end)
    return text[start:end].replace("\n", " ").strip()
