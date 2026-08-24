"""Markdown note parsing for the mechanical memory index."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from . import frontmatter
from .index_config import WIKILINK_RE
from .index_types import NoteEntry
from .lexical import tokenize
from .json_types import JsonObject


def note_entry(path: Path, rel: str) -> NoteEntry | None:
    """Parse one note file into a complete index entry."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        stat = path.stat()
    except OSError:
        return None
    metadata, body = frontmatter.parse(text)
    title = str(metadata.get("title") or path.stem)
    raw_tags = metadata.get("tags")
    tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []
    raw_confidence = metadata.get("confidence", 0.5)
    match raw_confidence:
        case bool() | int() | float() | str():
            try:
                confidence = float(raw_confidence)
            except ValueError:
                confidence = 0.5
        case _:
            confidence = 0.5
    terms: dict[str, int] = {}
    for token in tokenize(" ".join([title, " ".join(tags), body])):
        terms[token] = terms.get(token, 0) + 1
    normalized_rel = rel.replace("\\", "/")
    zone = normalized_rel.rsplit("/", 1)[0] if "/" in normalized_rel else ""
    summary = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            summary = stripped[:120]
            break
    return {
        "title": title,
        "rel": normalized_rel,
        "zone": zone,
        "type": str(metadata.get("type", "topic")),
        "tags": tags,
        "links": sorted(set(WIKILINK_RE.findall(text))),
        "created": str(metadata.get("created", "")),
        "updated": str(metadata.get("updated", "")),
        "confidence": confidence,
        "polarity": str(metadata.get("polarity") or "positive"),
        "expires_at": (
            str(metadata["expires_at"]) if metadata.get("expires_at") else None
        ),
        "summary": summary,
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "doclen": sum(terms.values()),
        "terms": terms,
    }


def entry_expired(entry: JsonObject | NoteEntry, today: date) -> bool:
    """Return whether an entry's optional expiry date is in the past."""
    raw = entry.get("expires_at")
    if not raw:
        return False
    try:
        return date.fromisoformat(str(raw)) < today
    except ValueError:
        return False
