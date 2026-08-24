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

import re

from .json_types import JsonObject, JsonValue


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
    meta = _parse_block(fm.splitlines(), 0, 0)[0] or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


# -- internals -------------------------------------------------------------

def _indent(s: str) -> int:
    return len(s) - len(s.lstrip(" "))


def _split_commas(s: str) -> list[str]:
    out: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in s:
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


def _parse_value(s: str) -> JsonValue:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_parse_value(x) for x in _split_commas(inner)] if inner else []
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~", ""):
        return None
    try:
        return int(s) if re.fullmatch(r"-?\d+", s) else float(s)
    except ValueError:
        return s


def _parse_block(
    lines: list[str],
    i: int,
    base: int,
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
                    entry[key.strip()] = _parse_value(val)
                sub, i = _parse_block(lines, i + 1, ind + 2)
                if isinstance(sub, dict):
                    entry.update(sub)
                items.append(entry)
            else:
                items.append(_parse_value(item))
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
        if val:
            mapping[key] = _parse_value(val)
            i += 1
        else:
            sub, i = _parse_block(lines, i + 1, ind + 1)
            mapping[key] = {} if sub is None else sub
    return result, i
