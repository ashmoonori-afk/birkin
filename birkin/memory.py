"""Semantic memory as an Obsidian vault ("compile over retrieve").

Memory is a directory of Obsidian-compatible markdown notes — each with YAML
frontmatter and ``[[wikilinks]]`` — rather than an opaque vector store. This
keeps knowledge transparent and editable in Obsidian, and is the *mandatory*
substrate for birkin's memory.

Notes are slug-named files (so ``[[Title]]`` resolves by basename in
Obsidian) organized into one-level **zone** directories — memory-palace
rooms; the vault root is the *inbox* and ``_archive`` is the soft-forget
zone. The ``type`` lives in frontmatter:
``person | project | preference | fact | topic | session``.

Retrieval is index-backed via :mod:`birkin.mnemosyne` (BM25 + usage dynamics
+ zone priority) plus ``[[wikilink]]`` graph traversal — no embeddings,
honoring the zero-dependency goal. (Embedding search is a documented future
upgrade.) See ``docs/mnemosyne-design.md``.

The public interface (``render()`` and ``tools()``) matches the previous simple
memory so the rest of birkin is unaffected.
"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .mnemosyne import (ARCHIVE_ZONE, IDENTITY_ZONE, TYPE_ZONE, Mnemosyne,
                        _entry_expired, tokenize)
from .mnemosyne import atomic_write as _atomic_write
from .mnemosyne import slug as _slug
from .skills import frontmatter

VALID_TYPES = {"person", "project", "preference", "fact", "topic", "session"}
VALID_POLARITIES = {"positive", "negative"}

# Per-slug write locks: two channel threads can write the same note concurrently
# (the gateway runs LLM turns outside its global lock), so serialize a note's
# read->check->write to stop lost updates / interleaved corruption.
_NOTE_LOCKS: dict[str, threading.Lock] = {}
_NOTE_LOCKS_GUARD = threading.Lock()


def _note_lock(slug: str) -> threading.Lock:
    with _NOTE_LOCKS_GUARD:
        lk = _NOTE_LOCKS.get(slug)
        if lk is None:
            lk = _NOTE_LOCKS[slug] = threading.Lock()
        return lk


class VersionMismatchError(ValueError):
    """Raised by write_note when expected_version does not match the on-disk
    version (optimistic concurrency control — no stale-snapshot overwrites)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VaultMemory:
    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or {}
        self.vault = config.vault_dir(self.cfg)
        self._dex: Mnemosyne | None = None

    @property
    def dex(self) -> Mnemosyne:
        """The mechanical index/dynamics engine (lazy; see mnemosyne.py)."""
        if self._dex is None:
            self._dex = Mnemosyne(self.vault)
        return self._dex

    # -- low-level note IO -------------------------------------------------

    def _resolve_path(self, title: str, note_type: str = "topic",
                      zone: str | None = None) -> Path:
        """Existing notes stay where they live; new notes are placed by the
        explicit ``zone`` or the mechanical type→zone map (Morpheus refines
        placement nightly via memory_rezone)."""
        s = _slug(title)
        rel = self.dex.resolve_rel(s)
        if rel:
            return self.vault / rel
        if zone is not None:
            z = "" if zone in ("", "inbox") else _slug(zone)[:32]
        else:
            z = TYPE_ZONE.get(note_type, "knowledge")
        return (self.vault / z / f"{s}.md") if z else self.vault / f"{s}.md"

    def _find_note(self, title: str) -> Path | None:
        rel = self.dex.resolve_rel(_slug(title))
        if rel and (self.vault / rel).is_file():
            return self.vault / rel
        return None

    def get_note(self, title: str) -> str | None:
        p = self._find_note(title)
        if p is None:
            return None
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        self.dex.record_access(p.stem)   # reading a note = using it
        return text

    def list_notes(self) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for entry in self.dex.entries().values():
            if entry["zone"] == ARCHIVE_ZONE:
                continue   # soft-forgotten; reachable via zone="_archive"
            if _is_expired(entry):
                continue   # TTL: drop expired notes from the index/router
            notes.append({
                "title": entry["title"],
                "type": entry["type"],
                "updated": entry["updated"],
                "confidence": entry["confidence"],
                "polarity": entry["polarity"],
                "zone": entry["zone"] or "inbox",
                "path": self.vault / entry["rel"],
            })
        return notes

    def purge_expired(self) -> int:
        """Delete notes whose ``expires_at`` is in the past; return the count.

        TTL notes are otherwise only *hidden* from search/render, so the vault
        grows without bound. Call this from the nightly maintenance routine — not
        on every read, since a read should not silently delete a user's files."""
        removed = 0
        for entry in self.dex.entries().values():
            if _is_expired(entry):
                try:
                    (self.vault / entry["rel"]).unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    def write_note(self, title: str, body: str, *, note_type: str = "topic",
                   tags: list[str] | None = None, links: list[str] | None = None,
                   confidence: float = 0.7, source: str | None = None,
                   append: bool = False, ttl_days: int | None = None,
                   polarity: str | None = None, zone: str | None = None,
                   expected_version: int | None = None) -> Path:
        """Create or update a note.

        ``zone`` places a **new** note in a specific palace zone directory
        (``"inbox"``/``""`` = vault root); existing notes never move here —
        use :meth:`rezone`. Without it, the type→zone map decides.

        Memory-OS controls:
        - ``ttl_days`` — auto-expire from the index/search/render after N days.
        - ``polarity`` — ``"positive"`` (default) or ``"negative"`` (a known
          failure; surfaced with a re-verify hint in the prompt digest).
        - ``expected_version`` — optimistic lock; raise
          :class:`VersionMismatchError` if it does not match the on-disk version.
        - **Evidence gate** — a brand-new note requires at least one ``source``.
        """
        note_type = note_type if note_type in VALID_TYPES else "topic"
        # Serialize the read->check->write for this note so concurrent writers
        # can't both pass the version check and clobber each other (lost update),
        # and so the file is never half-written under a reader. Path resolution
        # happens INSIDE the lock: rezone() takes the same lock, so a move can't
        # slip between resolve and write (stale path -> duplicate note).
        with _note_lock(_slug(title)):
            p = self._resolve_path(title, note_type, zone)
            created = date.today().isoformat()
            sources: list[str] = []
            existing_body = ""
            existing_polarity: str | None = None
            existing_version = 0
            if p.is_file():
                old = p.read_text(encoding="utf-8", errors="replace")
                meta, old_body = frontmatter.parse(old)
                created = str(meta.get("created", created))
                old_sources = meta.get("sources")
                if isinstance(old_sources, list):
                    sources = [str(s) for s in old_sources]
                existing_body = old_body.strip()
                existing_polarity = str(meta.get("polarity") or "") or None
                try:
                    existing_version = int(meta.get("version") or 0)
                except (TypeError, ValueError):
                    existing_version = 0

            if expected_version is not None and int(expected_version) != existing_version:
                raise VersionMismatchError(
                    f"expected version {expected_version}, on-disk {existing_version}")

            if source and source not in sources:
                sources.append(source)

            # Evidence-gated writes (opt-in via `evidence_required: true` in config):
            # a new note with no prior sources and none provided is refused.
            if not sources and self.cfg.get("evidence_required"):
                raise ValueError(
                    "memory writes require at least one `source` for a new note "
                    "(evidence_required is enabled in config)")

            if polarity is not None and polarity not in VALID_POLARITIES:
                raise ValueError(
                    f"polarity must be one of {sorted(VALID_POLARITIES)}, got {polarity!r}")
            pol = polarity or existing_polarity or "positive"
            if pol not in VALID_POLARITIES:   # defensive — bad on-disk value
                pol = "positive"

            body = body.strip()
            if append and existing_body:
                body = existing_body + "\n\n" + body

            # Ensure linked notes appear as wikilinks in a Related section.
            links = links or []
            if links:
                related = " · ".join(f"[[{link}]]" for link in links)
                if "## Related" not in body:
                    body += f"\n\n## Related\n{related}"

            expires_at = None
            if ttl_days is not None and int(ttl_days) > 0:
                from datetime import timedelta
                expires_at = (date.today() + timedelta(days=int(ttl_days))).isoformat()

            fm = _compose_frontmatter(
                title=title, note_type=note_type, created=created,
                updated=_now_iso()[:10], confidence=confidence,
                sources=sources, tags=tags or [], expires_at=expires_at,
                polarity=pol, version=existing_version + 1)
            _atomic_write(p, fm + body + "\n")
            self.dex.note_written(p)
            self.dex.record_access(_slug(title))   # writing = using
            return p

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Index-backed search (BM25 × dynamics × zone priority). Reads only
        the top ``limit`` note files for snippets — never the whole vault."""
        # tokenize() (not whitespace split) so the snippet finder sees the
        # SAME tokens BM25 matched on — for Korean that means Hangul bigrams,
        # which DO occur literally in the body ("안녕" in "안녕하십니까"),
        # while the whole query word often does not.
        terms = tokenize(query)
        out: list[dict[str, Any]] = []
        for h in self.dex.search(query, limit=limit):
            body = h["summary"]
            try:
                _, parsed = frontmatter.parse(
                    (self.vault / h["rel"]).read_text(encoding="utf-8",
                                                      errors="replace"))
                body = parsed or body
            except OSError:
                pass
            # related capped at 3 — the §5.5 top-k link policy: beyond a
            # note's closest neighbors, extra links are injection dead weight.
            out.append({"title": h["slug"],
                        "snippet": _snippet(body, terms),
                        "zone": h["zone"] or "inbox",
                        "related": [_slug(t) for t in h["links"][:3]]})
        return out

    def near_duplicates(self, title: str, body: str,
                        limit: int = 3) -> list[tuple[str, float]]:
        """Mechanical near-duplicate candidates for a note about to be (or
        just) written: token-set cosine between the new text and each BM25
        candidate's indexed ``terms`` (already in the index — no extra I/O).

        Adopted from TDAI's write-time candidate recall (docs/
        tdai-comparison.md 차용 A): the *recall* is mechanical and instant;
        the *judgment* (supersede/merge/archive) stays with the nightly
        curator. Returns [(slug, similarity)], highest first; the note's own
        slug is excluded so updating a note never flags itself.
        """
        import math
        new_tokens = set(tokenize(f"{title} {body}"))
        if not new_tokens:
            return []
        self_slug = _slug(title)
        out: list[tuple[str, float]] = []
        seen: set[str] = set()
        query = f"{title} {body[:400]}"
        entries = self.dex.entries()   # one refresh/copy, not one per candidate
        for h in self.dex.search(query, limit=limit + 2):
            slug = h["slug"]
            if slug == self_slug or slug in seen:
                continue
            seen.add(slug)
            terms = set((entries.get(slug) or {}).get("terms", {}))
            if not terms:
                continue
            sim = len(new_tokens & terms) / math.sqrt(len(new_tokens)
                                                      * len(terms))
            out.append((slug, round(sim, 3)))
        out.sort(key=lambda t: -t[1])
        return out[:limit]

    def add_link(self, from_title: str, to_title: str) -> bool:
        text = self.get_note(from_title)
        if text is None:
            return False
        if f"[[{to_title}]]" in text:
            return True
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

    # -- palace maintenance --------------------------------------------------

    def rezone(self, title: str, zone: str) -> Path:
        """Move a note to another zone (Morpheus's placement instrument)."""
        with _note_lock(_slug(title)):
            return self.dex.rezone(_slug(title), zone)

    def reindex(self) -> dict[str, int]:
        """Force-rebuild the vault index; returns stats (``birkin reindex``)."""
        return self.dex.rebuild()

    # -- prompt digest -----------------------------------------------------

    def render(self, limit: int = 10) -> str:
        """Zone-aware digest for the system prompt: identity first, then
        zones by priority (effective strength orders notes inside a zone),
        inbox last as a standing filing nudge. ``_archive`` is excluded.

        Default trimmed 25 -> 10 (token diet D4): the digest is a map, not
        the territory — beyond identity + the hottest notes, agents reach
        for memory_search anyway, and each digest line costs every turn.
        """
        dex = self.dex
        now = datetime.now(timezone.utc)
        by_zone: dict[str, list[tuple[float, dict[str, Any]]]] = {}
        for s, e in dex.entries().items():
            if e["zone"] == ARCHIVE_ZONE or _is_expired(e):
                continue
            by_zone.setdefault(e["zone"], []).append(
                (dex.effective_of(s, now), e))
        if not by_zone:
            return ""
        pri = dex.zone_priorities(today=now.date())
        mid = sorted((z for z in by_zone if z not in ("", IDENTITY_ZONE)),
                     key=lambda z: (-pri.get(z, 0.0), z))
        order = ([IDENTITY_ZONE] if IDENTITY_ZONE in by_zone else []) \
            + mid + ([""] if "" in by_zone else [])
        total = sum(len(v) for v in by_zone.values())
        lines = [f"Vault: {self.vault} ({total} notes). "
                 f"Use memory_search / memory_get_note for details."]
        left = limit
        for z in order:
            if left <= 0:
                break
            group = sorted(by_zone[z],
                           key=lambda t: (t[0], t[1]["updated"]),
                           reverse=True)
            cap = min(left, 5) if z == IDENTITY_ZONE else left
            lines.append(f"[{z or 'inbox'}]")
            for _eff, e in group[:cap]:
                tag = (" ⚠ known failure — re-verify"
                       if e.get("polarity") == "negative" else "")
                lines.append(
                    f"- [[{e['title']}]] ({e['type']}){tag}: {e['summary']}")
                left -= 1
                if left <= 0:
                    break
        return "\n".join(lines)

    # -- tools -------------------------------------------------------------

    def tools(self) -> list[Any]:   # list[Tool]; imported lazily (cycle)
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
            try:
                p = self.write_note(
                    title, body,
                    note_type=str(inp.get("type", "topic")),
                    tags=inp.get("tags") or [],
                    links=inp.get("links") or [],
                    confidence=float(inp.get("confidence", 0.7) or 0.7),
                    source=inp.get("source") or "conversation",
                    append=bool(inp.get("append", False)),
                    ttl_days=int(inp["ttl_days"]) if inp.get("ttl_days") else None,
                    polarity=inp.get("polarity"),
                    zone=inp.get("zone"),
                    expected_version=(int(inp["expected_version"])
                                      if inp.get("expected_version") is not None
                                      else None))
            except VersionMismatchError as exc:
                return ToolResult(f"write rejected (stale version): {exc}",
                                  is_error=True)
            msg = f"Wrote note [[{title}]] -> {p}"
            # Write-time near-duplicate advisory (TDAI-adopted, mechanical,
            # never blocking): flag likely twins so the writer can supersede
            # or link now; the nightly curator remains the final judge.
            try:
                dups = self.near_duplicates(title, body)
            except Exception:
                dups = []
            for slug, sim in dups:
                if sim >= 0.60:
                    msg += (f"\n⚠ near-duplicate of [[{slug}]] (sim {sim}) — "
                            f"consider append/supersede instead of a new note.")
                elif sim >= 0.35:
                    msg += (f"\n· related to [[{slug}]] (sim {sim}) — "
                            f"consider memory_link.")
            return ToolResult(msg)

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

        def memory_related(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            title = (inp.get("title") or "").strip()
            if not title:
                return ToolResult("memory_related needs a title.",
                                  is_error=True)
            hits = self.dex.related(_slug(title),
                                    limit=int(inp.get("limit", 5) or 5))
            if not hits:
                return ToolResult("No related candidates.")
            return ToolResult("\n".join(
                f"- [[{h['title']}]] (zone: {h['zone'] or 'inbox'}): "
                f"{h['summary']}" for h in hits))

        def memory_rezone(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            title = (inp.get("title") or "").strip()
            zone = (inp.get("zone") or "").strip()
            if not (title and zone):
                return ToolResult("memory_rezone needs title and zone.",
                                  is_error=True)
            try:
                p = self.rezone(title, zone)
            except (ValueError, OSError) as exc:
                return ToolResult(f"rezone failed: {exc}", is_error=True)
            return ToolResult(f"Moved [[{title}]] to zone '{zone}' ({p}).")

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
                                  "description": "auto-expire after N days"},
                     "polarity": {"type": "string",
                                  "enum": ["positive", "negative"],
                                  "description": "use 'negative' for known failures"},
                     "zone": {"type": "string",
                              "description": "palace zone for a NEW note "
                                             "(e.g. projects, people; "
                                             "'inbox' = vault root)"},
                     "expected_version": {"type": "integer",
                                          "description": "optimistic-lock check"}},
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
            Tool(name="memory_related",
                 description="Mechanical candidates for notes related to a "
                             "given note (BM25 over its own terms, excluding "
                             "already-linked). Judge which are truly related, "
                             "then record real ones with memory_link.",
                 input_schema={"type": "object", "properties": {
                     "title": {"type": "string"},
                     "limit": {"type": "integer"}}, "required": ["title"]},
                 fn=memory_related),
            Tool(name="memory_rezone",
                 description="Move a note to another zone of the memory "
                             "palace ('_archive' soft-forgets, 'inbox' is "
                             "the vault root).",
                 input_schema={"type": "object", "properties": {
                     "title": {"type": "string"},
                     "zone": {"type": "string"}},
                     "required": ["title", "zone"]},
                 fn=memory_rezone),
        ]


# -- module helpers --------------------------------------------------------

def _compose_frontmatter(*, title: str, note_type: str, created: str,
                         updated: str, confidence: float,
                         sources: list[str], tags: list[str],
                         expires_at: str | None = None,
                         polarity: str = "positive",
                         version: int = 1) -> str:
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
        f"polarity: {polarity}\n"
        f"version: {int(version)}\n"
        f"sources: [{src}]\n"
        f"tags: [{tg}]\n"
        + ttl_line
        + "---\n\n"
    )


def _is_expired(meta: dict[str, Any]) -> bool:
    """True if ``meta['expires_at']`` is a date strictly in the past."""
    return _entry_expired(meta, date.today())


def _snippet(text: str, terms: list[str] | str, width: int = 240) -> str:
    """Best multi-term window: the ``width``-char span containing the most
    DISTINCT query terms (earliest on ties); falls back to the head.

    The old single-term/100-char snippet routinely missed the passage that
    made a note relevant, pushing agents to fetch whole notes — the dominant
    context-token cost (benchmarks/bench_token_diet.py). A denser snippet is
    the cheap fix: pay ~240 chars in the search result, save a full-note read.
    """
    if isinstance(terms, str):
        terms = [terms]
    low = text.lower()
    hits: list[tuple[int, str]] = []              # (position, term)
    for term in {t for t in terms if t}:
        start = 0
        while True:
            i = low.find(term, start)
            if i < 0:
                break
            hits.append((i, term))
            start = i + 1
    if not hits:
        return text.strip()[:width]
    hits.sort()
    from collections import Counter
    inwin: Counter = Counter()
    best_start, best_distinct = hits[0][0], 1
    j = 0
    for i, (pos, term) in enumerate(hits):
        inwin[term] += 1
        while hits[j][0] < pos - width:
            inwin[hits[j][1]] -= 1
            if not inwin[hits[j][1]]:
                del inwin[hits[j][1]]
            j += 1
        if len(inwin) > best_distinct:
            best_distinct, best_start = len(inwin), hits[j][0]
    # The winning window's content spans [best_start, best_start + width);
    # the left context pad must EXTEND the slice, not shift it, or the
    # right-edge hit that made this window best falls off the end.
    start = max(0, best_start - width // 8)
    return text[start:best_start + width].replace("\n", " ").strip()


def _title_from(note: str) -> str:
    words = re.sub(r"\s+", " ", note.strip()).split(" ")
    return " ".join(words[:6])[:60] or "Note"


# Backwards-compatible alias used by runtime.py
Memory = VaultMemory
