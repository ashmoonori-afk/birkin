"""A small YAML-subset parser for ``SKILL.md`` frontmatter.

We intentionally avoid a PyYAML dependency. This parser handles the subset
used by skill frontmatter:

- ``key: value`` scalars (strings, ints, floats, booleans, null)
- quoted strings (``"..."`` / ``'...'``)
- inline lists ``[a, b, c]``
- nested mappings via indentation (e.g. ``metadata.hermes.tags``)
- block lists (``- item``)

It is forgiving: anything it cannot parse degrades to a raw string rather than
raising.
"""

from __future__ import annotations

import json
import re

from .json_types import JsonObject, JsonValue, load_json

SOURCES_ENCODING_KEY = "sources_encoding"
SOURCES_ENCODING_JSON_V1 = "json-v1"


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_text, body). No frontmatter -> ('', text)."""
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return "", text


def parse(text: str) -> tuple[JsonObject, str]:
    """Parse a full SKILL.md string into (meta, body)."""
    fm, body = split_frontmatter(text)
    if not fm:
        return {}, body
    lines = fm.splitlines()
    marked = _top_level_json_sources(lines)
    meta = _parse_block(lines, 0, 0, marked)[0] or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


# -- internals -------------------------------------------------------------


def _indent(s: str) -> int:
    return len(s) - len(s.lstrip(" "))


def _top_level_json_sources(lines: list[str]) -> bool:
    """Return whether an unindented top-level marker enables JSON sources."""
    marker: JsonValue = None
    found = False
    for raw in lines:
        if not raw.strip() or _indent(raw) != 0:
            continue
        key, sep, val = raw.strip().partition(":")
        if sep and key.strip() == SOURCES_ENCODING_KEY:
            marker = _parse_value(val)
            found = True
    return found and marker == SOURCES_ENCODING_JSON_V1


def _decode_json_sources(val: str) -> JsonValue:
    """Decode a marked ``sources`` value, degrading to the raw string."""
    stripped = val.strip()
    try:
        decoded = load_json(stripped)
    except json.JSONDecodeError:
        return stripped
    if not isinstance(decoded, list):
        return stripped
    if not all(isinstance(item, str) for item in decoded):
        return stripped
    return [str(item) for item in decoded]


def _quote_opens(s: str, start: int) -> bool:
    """Return whether a quote at ``start`` begins a value rather than sits in one."""
    position = start - 1
    while position >= 0 and s[position] in " \t":
        position -= 1
    if position < 0:
        return True
    return s[position] in "[{,"


def _split_commas(s: str) -> list[str]:
    out: list[str] = []
    depth = 0
    quote: str | None = None
    quote_end = -1
    buf: list[str] = []
    for index, ch in enumerate(s):
        if quote is not None:
            buf.append(ch)
            if ch == quote and index >= quote_end:
                following = index + 1
                while following < len(s) and s[following] in " \t":
                    following += 1
                if following == len(s) or s[following] in ",]}":
                    quote = None
            continue
        if ch in "\"'" and _quote_opens(s, index):
            quote = ch
            quote_end = _closing_quote(s, index)
            buf.append(ch)
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def _closing_quote(s: str, start: int) -> int:
    """Return the index of the quote that closes the value opened at ``start``."""
    quote = s[start]
    index = start + 1
    while index < len(s):
        if s[index] == quote:
            following = index + 1
            while following < len(s) and s[following] in " \t":
                following += 1
            if following == len(s) or s[following] in ",]}":
                return index
        index += 1
    return len(s)


def _parse_value(s: str) -> JsonValue:
    return _parse_scalar(s, marked_sources=False)


def _parse_scalar(s: str, *, marked_sources: bool) -> JsonValue:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if marked_sources:
            decoded = _decode_json_sources(s)
            if decoded is not None:
                return decoded
        return (
            [
                _parse_scalar(x, marked_sources=marked_sources)
                for x in _split_commas(inner)
            ]
            if inner
            else []
        )
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~", ""):
        return None
    try:
        return int(s) if re.fullmatch(r"-?\d+", s) else float(s)
    except ValueError:
        return s


def _parse_marked_sources(raw: str) -> JsonValue:
    """Parse a marked ``sources`` line without any legacy reinterpretation."""
    _key, sep, val = raw.partition(":")
    return _decode_json_sources(val if sep else raw)


def _parse_block(
    lines: list[str],
    i: int,
    base: int,
    marked_sources: bool = False,
) -> tuple[JsonValue | None, int]:
    """Parse lines[i:] at indentation >= base into a dict or list.

    Returns (obj, next_index).
    """
    result: JsonValue | None = None
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        ind = _indent(raw)
        if ind < base:
            break
        content = raw.strip()

        if content.startswith("- "):  # block list item
            match result:
                case None:
                    items: list[JsonValue] = []
                    result = items
                case list() as items:
                    pass
                case _:
                    message = "mixed frontmatter list and mapping"
                    raise TypeError(message)
            item = content[2:].strip()
            if ":" in item and not item.startswith("["):
                key, _, val = item.partition(":")
                entry: JsonObject = {}
                if val.strip():
                    entry[key.strip()] = _parse_scalar(val, marked_sources=False)
                sub, i = _parse_block(lines, i + 1, ind + 2)
                if isinstance(sub, dict):
                    entry.update(sub)
                items.append(entry)
            else:
                items.append(_parse_scalar(item, marked_sources=False))
                i += 1
            continue

        # mapping entry
        match result:
            case None:
                mapping: JsonObject = {}
                result = mapping
            case dict() as mapping:
                pass
            case _:
                message = "mixed frontmatter mapping and list"
                raise TypeError(message)
        key, _, val = content.partition(":")
        key = key.strip()
        val = val.strip()
        if base == 0 and marked_sources and key == "sources":
            mapping[key] = _parse_marked_sources(raw)
            i += 1
        elif val:
            mapping[key] = _parse_scalar(val, marked_sources=False)
            i += 1
        else:
            sub, i = _parse_block(lines, i + 1, ind + 1)
            mapping[key] = {} if sub is None else sub
    return result, i
