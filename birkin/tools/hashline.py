"""Hash-anchored line editing — make in-loop file edits refuse stale writes.

birkin's own agent loop (API / local-CLI providers) edits files by reading then
writing. A blind ``write_file`` overwrite loses any change made since the read,
and a naive find/replace can hit the wrong place. Hashline (idea borrowed from
oh-my-openagent, in turn from oh-my-pi; see ``docs/v2.md`` #2) tags every line
the agent reads with a short **content hash** — ``{line}#{hash}| {text}`` — and
``edit_text`` applies a change to line *N* **only if** that line still hashes to
the value the agent saw. A mismatch (the file changed underneath) is rejected
*atomically* (no partial write); the agent re-reads and retries.

Pure standard library. The functions here are pure; I/O lives in ``files.py``.
"""

from __future__ import annotations

import hashlib
from typing import Any

# 4 hex chars (16 bits) per line: collisions are per-line-number only (we compare
# line N's stored hash to line N's current hash), so 1/65536 is ample.
_HASH_LEN = 4


def line_hash(line: str) -> str:
    """Short, stable content hash of a single line (no trailing newline)."""
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:_HASH_LEN]


def annotate(text: str) -> str:
    """Tag each line with ``{lineno}#{hash}| `` so edits can be hash-anchored.

    1-indexed. The ``| `` separator is visual only — strip it back off with
    :func:`strip` if you need the raw text.
    """
    out = []
    for i, ln in enumerate(text.split("\n"), 1):
        out.append(f"{i}#{line_hash(ln)}| {ln}")
    return "\n".join(out)


def strip(annotated: str) -> str:
    """Inverse of :func:`annotate` — drop the ``{lineno}#{hash}| `` prefixes."""
    out = []
    for ln in annotated.split("\n"):
        head, sep, rest = ln.partition("| ")
        # only strip when the head looks like "<n>#<hash>"
        num, dot, h = head.partition("#")
        out.append(rest if (sep and dot and num.isdigit()) else ln)
    return "\n".join(out)


def edit_text(text: str, edits: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Apply hash-anchored line edits, all-or-nothing.

    Each edit is ``{"line": <1-indexed int>, "hash": <str>, "new": <str>}``;
    ``new`` may be multi-line or ``""`` (blank the line). Returns
    ``(new_text, errors)``. If ``errors`` is non-empty NOTHING is applied and
    ``new_text`` is the original ``text`` — so a stale/mismatched edit can never
    corrupt the file.
    """
    lines = text.split("\n")
    n_lines = len(lines)
    errors: list[str] = []
    seen: set[int] = set()
    norm: list[tuple[int, str]] = []  # (0-indexed line, new text)

    for e in edits:
        try:
            ln = int(e["line"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"edit {e!r}: missing/invalid 'line'")
            continue
        if ln in seen:
            errors.append(f"line {ln}: duplicate edit in the same call")
            continue
        seen.add(ln)
        if not (1 <= ln <= n_lines):
            errors.append(f"line {ln}: out of range (file has {n_lines} lines)")
            continue
        want = str(e.get("hash", ""))
        have = line_hash(lines[ln - 1])
        if want != have:
            errors.append(
                f"line {ln}: stale hash (you sent #{want}, file now has #{have}) "
                f"— re-read with annotate=true and retry")
            continue
        if "new" not in e:
            errors.append(f"line {ln}: missing 'new' replacement text")
            continue
        norm.append((ln - 1, str(e["new"])))

    if errors:
        return text, errors

    for idx, new in norm:
        lines[idx] = new
    return "\n".join(lines), []
