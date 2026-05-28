"""Semantic memory as an Obsidian vault ("compile over retrieve").

Memory is a directory of Obsidian-compatible markdown notes — each with YAML
frontmatter and ``[[wikilinks]]`` — rather than an opaque vector store. This
keeps knowledge transparent and editable in Obsidian, and is the *mandatory*
substrate for birkin's memory.

Notes are flat files named by a slug of their title (so ``[[Title]]`` resolves
by basename in Obsidian). The ``type`` lives in frontmatter:
``person | project | preference | fact | topic | session``.

Search is keyword/substring over note text plus ``[[wikilink]]`` graph
traversal — no embeddings, honoring the zero-dependency goal. (Embedding
search is a documented future upgrade.)

The public interface (``render()`` and ``tools()``) matches the previous simple
memory so the rest of birkin is unaffected.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .skills import frontmatter

VALID_TYPES = {"person", "project", "preference", "fact", "topic", "session"}
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _slug(title: str) -> str:
    s = re.sub(r"[^\w\s-]", "", title.strip().lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "note"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VaultMemory:
    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or {}
        self.vault = config.vault_dir(self.cfg)

    # -- low-level note IO -------------------------------------------------

    def _path(self, title: str) -> Path:
        return self.vault / f"{_slug(title)}.md"

    def get_note(self, title: str) -> str | None:
        p = self._path(title)
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
        # fall back to a case-insensitive title match
        target = _slug(title)
        for f in self.vault.glob("*.md"):
            if f.stem == target:
                return f.read_text(encoding="utf-8", errors="replace")
        return None

    def list_notes(self) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for f in self.vault.glob("*.md"):
            try:
                meta, _ = frontmatter.parse(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if _is_expired(meta):
                continue   # TTL: drop expired notes from the index/router
            notes.append({
                "title": meta.get("title", f.stem),
                "type": meta.get("type", "topic"),
                "updated": meta.get("updated", ""),
                "confidence": meta.get("confidence", 0.5),
                "path": f,
            })
        return notes

    def write_note(self, title: str, body: str, *, note_type: str = "topic",
                   tags: list[str] | None = None, links: list[str] | None = None,
                   confidence: float = 0.7, source: str | None = None,
                   append: bool = False, ttl_days: int | None = None) -> Path:
        """Create or update a note. Preserves ``created`` and merges sources.

        ``ttl_days``: optional Time-To-Live; the note auto-expires from the
        index/search/render after that many days (still readable by name)."""
        note_type = note_type if note_type in VALID_TYPES else "topic"
        p = self._path(title)
        created = date.today().isoformat()
        sources: list[str] = []
        existing_body = ""
        if p.is_file():
            old = p.read_text(encoding="utf-8", errors="replace")
            meta, old_body = frontmatter.parse(old)
            created = str(meta.get("created", created))
            old_sources = meta.get("sources")
            if isinstance(old_sources, list):
                sources = [str(s) for s in old_sources]
            existing_body = old_body.strip()

        if source and source not in sources:
            sources.append(source)

        body = body.strip()
        if append and existing_body:
            body = existing_body + "\n\n" + body

        # Ensure linked notes appear as wikilinks in a Related section.
        links = links or []
        if links:
            related = " · ".join(f"[[{l}]]" for l in links)
            if "## Related" not in body:
                body += f"\n\n## Related\n{related}"

        expires_at = None
        if ttl_days is not None and int(ttl_days) > 0:
            from datetime import timedelta
            expires_at = (date.today() + timedelta(days=int(ttl_days))).isoformat()

        fm = _compose_frontmatter(
            title=title, note_type=note_type, created=created,
            updated=_now_iso()[:10], confidence=confidence,
            sources=sources, tags=tags or [], expires_at=expires_at)
        p.write_text(fm + body + "\n", encoding="utf-8")
        return p

    def search(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        """Keyword/substring search across the vault, ranked by hit count."""
        terms = [t for t in re.split(r"\s+", query.lower()) if t]
        if not terms:
            return []
        hits: list[tuple[int, dict[str, str]]] = []
        for f in self.vault.glob("*.md"):
            text = f.read_text(encoding="utf-8", errors="replace")
            meta, body = frontmatter.parse(text)
            if _is_expired(meta):
                continue
            low = text.lower()
            score = sum(low.count(t) for t in terms)
            if score:
                snippet = _snippet(body or text, terms[0])
                hits.append((score, {"title": f.stem, "snippet": snippet}))
        hits.sort(key=lambda x: x[0], reverse=True)
        return [h[1] for h in hits[:limit]]

    def neighbors(self, title: str) -> list[str]:
        """Titles linked from a note (outgoing ``[[wikilinks]]``)."""
        text = self.get_note(title) or ""
        return sorted(set(WIKILINK_RE.findall(text)))

    def add_link(self, from_title: str, to_title: str) -> bool:
        text = self.get_note(from_title)
        if text is None:
            return False
        if f"[[{to_title}]]" in text:
            return True
        p = self._path(from_title)
        meta, body = frontmatter.parse(text)
        body = body.rstrip()
        if "## Related" in body:
            body += f" · [[{to_title}]]"
        else:
            body += f"\n\n## Related\n[[{to_title}]]"
        # rewrite preserving frontmatter
        self.write_note(meta.get("title", from_title), body,
                        note_type=str(meta.get("type", "topic")),
                        confidence=float(meta.get("confidence", 0.7) or 0.7))
        return True

    # -- prompt digest -----------------------------------------------------

    def render(self, limit: int = 25) -> str:
        """A compact digest for the system prompt (recency + confidence)."""
        notes = self.list_notes()
        if not notes:
            return ""

        def rank(n: dict[str, Any]) -> tuple:
            try:
                conf = float(n.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            return (str(n.get("updated", "")), conf)

        notes.sort(key=rank, reverse=True)
        lines = [f"Vault: {self.vault} ({len(notes)} notes). "
                 f"Use memory_search / memory_get_note for details."]
        for n in notes[:limit]:
            first = _first_line(n["path"])
            lines.append(f"- [[{n['title']}]] ({n['type']}): {first}")
        return "\n".join(lines)

    # -- tools -------------------------------------------------------------

    def tools(self):
        from .tools import Tool, ToolContext, ToolResult

        def remember(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            note = inp.get("note")
            key, value = inp.get("key"), inp.get("value")
            if key and value:
                self.write_note(f"Profile - {key}", f"{key}: {value}",
                                note_type="preference", confidence=0.9,
                                source="conversation")
                return ToolResult(f"Remembered {key} = {value}")
            if note:
                title = inp.get("title") or _title_from(note)
                self.write_note(title, str(note), note_type="fact",
                                confidence=0.7, source="conversation")
                return ToolResult(f"Noted as [[{title}]].")
            return ToolResult("remember needs note, or key+value.", is_error=True)

        def memory_write_note(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            title = (inp.get("title") or "").strip()
            body = (inp.get("body") or "").strip()
            if not (title and body):
                return ToolResult("memory_write_note needs title and body.",
                                  is_error=True)
            p = self.write_note(
                title, body,
                note_type=str(inp.get("type", "topic")),
                tags=inp.get("tags") or [],
                links=inp.get("links") or [],
                confidence=float(inp.get("confidence", 0.7) or 0.7),
                source=inp.get("source") or "conversation",
                append=bool(inp.get("append", False)),
                ttl_days=int(inp["ttl_days"]) if inp.get("ttl_days") else None)
            return ToolResult(f"Wrote note [[{title}]] -> {p}")

        def memory_search(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            results = self.search(inp.get("query", ""),
                                  limit=int(inp.get("limit", 8)))
            if not results:
                return ToolResult("No matching notes.")
            return ToolResult("\n".join(
                f"- [[{r['title']}]]: {r['snippet']}" for r in results))

        def memory_get_note(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            text = self.get_note(inp.get("title", ""))
            return (ToolResult(text) if text is not None
                    else ToolResult(f"No note titled {inp.get('title')!r}.",
                                    is_error=True))

        def memory_link(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            ok = self.add_link(inp.get("from", ""), inp.get("to", ""))
            return (ToolResult("Linked.") if ok
                    else ToolResult("Source note not found.", is_error=True))

        return [
            Tool(name="remember",
                 description="Quickly persist a durable fact about the user or "
                             "project. Use key+value for stable attributes, or "
                             "note for a free-form fact.",
                 input_schema={"type": "object", "properties": {
                     "note": {"type": "string"}, "title": {"type": "string"},
                     "key": {"type": "string"}, "value": {"type": "string"}}},
                 fn=remember),
            Tool(name="memory_write_note",
                 description="Create or update an Obsidian vault note (semantic "
                             "memory). Link related notes via the 'links' list "
                             "(rendered as [[wikilinks]]).",
                 input_schema={"type": "object", "properties": {
                     "title": {"type": "string"},
                     "body": {"type": "string", "description": "Markdown body"},
                     "type": {"type": "string",
                              "enum": sorted(VALID_TYPES)},
                     "tags": {"type": "array", "items": {"type": "string"}},
                     "links": {"type": "array", "items": {"type": "string"},
                               "description": "Titles of related notes"},
                     "confidence": {"type": "number"},
                     "source": {"type": "string"},
                     "append": {"type": "boolean"},
                     "ttl_days": {"type": "integer",
                                  "description": "auto-expire after N days"}},
                     "required": ["title", "body"]},
                 fn=memory_write_note),
            Tool(name="memory_search",
                 description="Keyword-search the semantic memory vault and get "
                             "back matching notes with snippets.",
                 input_schema={"type": "object", "properties": {
                     "query": {"type": "string"},
                     "limit": {"type": "integer"}}, "required": ["query"]},
                 fn=memory_search),
            Tool(name="memory_get_note",
                 description="Read a memory note in full by title.",
                 input_schema={"type": "object", "properties": {
                     "title": {"type": "string"}}, "required": ["title"]},
                 fn=memory_get_note),
            Tool(name="memory_link",
                 description="Add a [[wikilink]] from one note to another.",
                 input_schema={"type": "object", "properties": {
                     "from": {"type": "string"}, "to": {"type": "string"}},
                     "required": ["from", "to"]},
                 fn=memory_link),
        ]


# -- module helpers --------------------------------------------------------

def _compose_frontmatter(*, title: str, note_type: str, created: str,
                         updated: str, confidence: float,
                         sources: list[str], tags: list[str],
                         expires_at: str | None = None) -> str:
    src = ", ".join(f'"{s}"' for s in sources)
    tg = ", ".join(str(t) for t in tags)
    ttl_line = f"expires_at: {expires_at}\n" if expires_at else ""
    return (
        "---\n"
        f"title: {title}\n"
        f"type: {note_type}\n"
        f"created: {created}\n"
        f"updated: {updated}\n"
        f"confidence: {confidence}\n"
        f"sources: [{src}]\n"
        f"tags: [{tg}]\n"
        + ttl_line
        + "---\n\n"
    )


def _is_expired(meta: dict[str, Any]) -> bool:
    """True if ``meta['expires_at']`` is a date strictly in the past."""
    raw = meta.get("expires_at")
    if not raw:
        return False
    try:
        return date.fromisoformat(str(raw)) < date.today()
    except ValueError:
        return False


def _first_line(path: Path) -> str:
    try:
        _, body = frontmatter.parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:120]
    return ""


def _snippet(text: str, term: str, width: int = 100) -> str:
    low = text.lower()
    i = low.find(term)
    if i < 0:
        return text.strip()[:width]
    start = max(0, i - width // 2)
    return text[start:start + width].replace("\n", " ").strip()


def _title_from(note: str) -> str:
    words = re.sub(r"\s+", " ", note.strip()).split(" ")
    return " ".join(words[:6])[:60] or "Note"


# Backwards-compatible alias used by runtime.py
Memory = VaultMemory
