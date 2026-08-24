"""Deterministic application of curation operations to note files."""

from __future__ import annotations

from pathlib import Path

from .atomic import atomic_write
from .index_config import ARCHIVE_ZONE
from .json_types import JsonObject
from .mnemosyne import Mnemosyne


def _required_string(operation: JsonObject, key: str) -> str:
    value = operation[key]
    if isinstance(value, str):
        return value
    message = f"accepted operation field {key!r} must be a string"
    raise TypeError(message)


def _title_of(index: Mnemosyne, note_slug: str) -> str:
    entry = index.note_meta(note_slug)
    return entry["title"] if entry else note_slug


def _append_related(
    vault: Path,
    index: Mnemosyne,
    note_slug: str,
    target_title: str,
) -> bool:
    entry = index.note_meta(note_slug)
    if entry is None:
        return False
    path = vault / entry["rel"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if f"[[{target_title}]]" in text:
        return False
    if "## Related" in text:
        updated = text.rstrip() + f"\n- [[{target_title}]]\n"
    else:
        updated = text.rstrip() + f"\n\n## Related\n- [[{target_title}]]\n"
    atomic_write(path, updated)
    index.note_written(path)
    return True


def _append_line(
    vault: Path,
    index: Mnemosyne,
    note_slug: str,
    line: str,
) -> bool:
    entry = index.note_meta(note_slug)
    if entry is None:
        return False
    path = vault / entry["rel"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if line in text:
        return False
    atomic_write(path, text.rstrip() + f"\n\n{line}\n")
    index.note_written(path)
    return True


def apply_plan(
    accepted: list[JsonObject],
    vault: Path,
    index: Mnemosyne,
) -> list[JsonObject]:
    """Apply validated operations and return observable effects."""
    effected: list[JsonObject] = []
    for operation in accepted:
        kind = _required_string(operation, "op")
        try:
            if kind == "rezone":
                note_slug = _required_string(operation, "slug")
                zone = _required_string(operation, "zone")
                _ = index.rezone(note_slug, zone)
                effected.append({"op": "rezone", "slug": note_slug, "zone": zone})
            elif kind == "archive":
                note_slug = _required_string(operation, "slug")
                _ = index.rezone(note_slug, ARCHIVE_ZONE)
                effected.append({"op": "archive", "slug": note_slug})
            elif kind == "link":
                left = _required_string(operation, "a")
                right = _required_string(operation, "b")
                changed_left = _append_related(
                    vault,
                    index,
                    left,
                    _title_of(index, right),
                )
                changed_right = _append_related(
                    vault,
                    index,
                    right,
                    _title_of(index, left),
                )
                if changed_left or changed_right:
                    effected.append({"op": "link", "a": left, "b": right})
            elif kind == "supersede":
                stale = _required_string(operation, "stale")
                replacement = _required_string(operation, "by")
                changed = _append_line(
                    vault,
                    index,
                    stale,
                    f"> Superseded by [[{_title_of(index, replacement)}]]",
                )
                _ = _append_related(
                    vault,
                    index,
                    replacement,
                    _title_of(index, stale),
                )
                if changed:
                    effected.append(
                        {"op": "supersede", "stale": stale, "by": replacement}
                    )
        except (ValueError, OSError) as exc:
            effected.append({"op": kind, "error": str(exc)})
    return effected
