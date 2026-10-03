"""Frontmatter composition, expiry, and search snippet formatting."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date

from .frontmatter import SOURCES_ENCODING_JSON_V1, SOURCES_ENCODING_KEY
from .index_types import NoteEntry
from .json_types import JsonObject, JsonValue
from .lexical import STEM_MARK, STEM_MIN, normalize_with_offsets, script


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
    encoded_sources = json.dumps(sources, ensure_ascii=True)
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
            f"{SOURCES_ENCODING_KEY}: {SOURCES_ENCODING_JSON_V1}\n",
            f"sources: {encoded_sources}\n",
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


def _word_char(character: str) -> bool:
    return character.isalnum() and script(character) not in ("cjk", "hangul")


def _stem_word_at(lowered: str, index: int) -> bool:
    """Return whether a word that ``tokenize`` would stem starts at ``index``."""
    if index and _word_char(lowered[index - 1]):
        return False
    end = index
    while end < len(lowered) and _word_char(lowered[end]):
        end += 1
    word = lowered[index:end]
    return word.isalpha() and len(word) >= STEM_MIN


def snippet(text: str, terms: list[str] | str, width: int = 240) -> str:
    """Return the densest query-term window, earliest on score ties."""
    match terms:
        case str():
            query_terms = [terms]
        case list():
            query_terms = terms
    lowered, offsets = normalize_with_offsets(text)
    hits: list[tuple[int, str]] = []
    for term in {term for term in query_terms if term}:
        is_stem = term.endswith(STEM_MARK)
        needle = term[: -len(STEM_MARK)] if is_stem else term
        start = 0
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            if not is_stem or _stem_word_at(lowered, index):
                hits.append((index, needle))
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
    end = min(len(lowered), max(best_start + width, best_end))
    return text[offsets[start]:offsets[end]].replace("\n", " ").strip()
