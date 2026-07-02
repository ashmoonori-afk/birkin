"""Past-conversation recall tools (hermes ``session_search_tool`` analog).

Full-text search over the saved session transcripts in ``sessions_dir()``
(including the reserved ``auto__*`` gateway/REPL autosaves), so the agent can
answer "what did we decide about X last week?" without the user re-pasting
history. Plain substring scoring — sessions are small JSON files and recall
beats ranking sophistication here.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import config

_MAX_FILES = 400          # newest-first cap; older sessions age out of recall
_SNIPPET = 160
_GET_CAP = 4000


def _transcript(path: Path) -> str:
    try:
        messages = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    from ..selfimprove import transcript_from_messages
    try:
        return transcript_from_messages(messages)
    except Exception:   # malformed message shapes must not break recall
        return ""


def _sessions(newest_first: bool = True) -> list[Path]:
    files = [f for f in config.sessions_dir().glob("*.json")]
    files.sort(key=lambda f: f.stat().st_mtime if f.exists() else 0,
               reverse=newest_first)
    return files[:_MAX_FILES]


def search_sessions(query: str, limit: int = 5) -> list[dict[str, Any]]:
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    hits: list[tuple[int, dict[str, Any]]] = []
    for f in _sessions():
        text = _transcript(f)
        if not text:
            continue
        low = text.lower()
        score = sum(low.count(t) for t in terms)
        if not score:
            continue
        i = low.find(terms[0])
        start = max(0, i - _SNIPPET // 2)
        snippet = text[start:start + _SNIPPET].replace("\n", " ").strip()
        try:
            day = datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()
        except OSError:
            day = ""
        hits.append((score, {"session": f.stem, "date": day,
                             "snippet": snippet}))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [h[1] for h in hits[:limit]]


def get_session(name: str) -> str | None:
    stem = Path(name).stem                      # tolerate "s1.json" or "s1"
    if not stem or stem != Path(stem).name:     # no path separators
        return None
    p = config.sessions_dir() / f"{stem}.json"
    if not p.is_file():
        return None
    text = _transcript(p)
    return text[:_GET_CAP] if text else None


def tools() -> list[Any]:
    from . import Tool, ToolContext, ToolResult

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
