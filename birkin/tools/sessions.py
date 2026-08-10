"""Past-conversation recall tools (hermes ``session_search_tool`` analog).

Full-text search over the saved session transcripts in ``sessions_dir()``
(including the reserved ``auto__*`` gateway/REPL autosaves), so the agent can
answer "what did we decide about X last week?" without the user re-pasting
history.

Ranking comes from a SQLite FTS5 index (``sessions_index``), which covers the
whole corpus and handles Korean via bigram shadow text. That index is only a
cache: when it cannot serve a query — no FTS5, corrupt database, a query that
survives tokenization badly — this module falls back to the original substring
scan over the newest files, so recall degrades rather than disappearing.
"""

from __future__ import annotations

import json
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from .. import config
from ._types import Tool, ToolContext, ToolResult

_MAX_FILES = 400          # newest-first cap; older sessions age out of recall
_SNIPPET = 160
_GET_CAP = 4000


def _transcript(path: Path) -> str:
    try:
        messages = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    transcript_from_messages = import_module(
        "birkin.selfimprove"
    ).transcript_from_messages
    try:
        return transcript_from_messages(messages)
    except Exception:   # malformed message shapes must not break recall
        return ""


def _sessions(newest_first: bool = True) -> list[Path]:
    files = [f for f in config.sessions_dir().glob("*.json")]
    files.sort(key=lambda f: f.stat().st_mtime if f.exists() else 0,
               reverse=newest_first)
    return files[:_MAX_FILES]


def _day(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    except OSError:
        return ""


def _snippet(text: str, terms: list[str]) -> str:
    """A window of the RAW transcript around the first matching term.

    Deliberately sliced from the prose rather than taken from FTS5's snippet(),
    which would happily quote the bigram shadow text back at the user.
    """
    low = text.lower()
    i = next((low.find(t) for t in terms if low.find(t) >= 0), -1)
    start = max(0, i - _SNIPPET // 2) if i >= 0 else 0
    return text[start:start + _SNIPPET].replace("\n", " ").strip()


def _hit(stem: str, terms: list[str]) -> dict[str, Any] | None:
    path = config.sessions_dir() / f"{stem}.json"
    text = _transcript(path)
    if not text:
        return None
    return {"session": stem, "date": _day(path),
            "snippet": _snippet(text, terms)}


def _scan(terms: list[str], limit: int) -> list[dict[str, Any]]:
    """Original substring scan — the no-index fallback path."""
    hits: list[tuple[int, dict[str, Any]]] = []
    for f in _sessions():
        text = _transcript(f)
        if not text:
            continue
        low = text.lower()
        score = sum(low.count(t) for t in terms)
        if not score:
            continue
        hits.append((score, {"session": f.stem, "date": _day(f),
                             "snippet": _snippet(text, terms)}))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [h[1] for h in hits[:limit]]


def search_sessions(query: str, limit: int = 5) -> list[dict[str, Any]]:
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    from .. import sessions_index
    ranked = sessions_index.search(query, limit=limit)
    if ranked is None:                    # index unusable — scan instead
        return _scan(terms, limit)
    return [h for h in (_hit(r["session"], terms) for r in ranked) if h]


def get_session(name: str) -> str | None:
    # Path(...).stem already discards any directory components (traversal is
    # neutralized by construction); the check below only rejects the residual
    # edge case where the stem itself isn't a plain name (e.g. "..").
    stem = Path(name).stem                      # tolerate "s1.json" or "s1"
    if not stem or stem != Path(stem).name:
        return None
    p = config.sessions_dir() / f"{stem}.json"
    if not p.is_file():
        return None
    text = _transcript(p)
    return text[:_GET_CAP] if text else None


def tools() -> list[Tool]:

    def session_search(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = (inp.get("query") or "").strip()
        if not query:
            return ToolResult("session_search needs a query.", is_error=True)
        results = search_sessions(query, limit=int(inp.get("limit", 5) or 5))
        if not results:
            return ToolResult("No past sessions match.")
        return ToolResult("\n".join(
            f"- {r['session']} ({r['date']}): {r['snippet']}"
            for r in results))

    def session_get(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
        text = get_session(inp.get("session") or "")
        return (ToolResult(text) if text
                else ToolResult("No such session.", is_error=True))

    return [
        Tool(name="session_search",
             description="Full-text search past conversation transcripts. "
                         "Use to recall earlier decisions/context before "
                         "asking the user to repeat themselves.",
             input_schema={"type": "object", "properties": {
                 "query": {"type": "string"},
                 "limit": {"type": "integer"}}, "required": ["query"]},
             fn=session_search),
        Tool(name="session_get",
             description="Read one past session transcript by id (from "
                         "session_search results).",
             input_schema={"type": "object", "properties": {
                 "session": {"type": "string"}}, "required": ["session"]},
             fn=session_get),
    ]
