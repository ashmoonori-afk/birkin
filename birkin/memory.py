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

import json
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from . import config, store, transcripts
from .mnemosyne import (ARCHIVE_ZONE, IDENTITY_ZONE, TYPE_ZONE, Mnemosyne,
                        _entry_expired, tokenize)
from .mnemosyne import atomic_write as _atomic_write
from .mnemosyne import slug as _slug
from .profile_actions import ProfileActions, validate_profile_text
from .profile_migration import LegacyPreference
from .rolefiles import ProfileEdit, ProfileStore
from .memory_scopes import (
    MemoryAccessPolicy,
    MemoryOperation,
    MemoryPolicyError,
    MemoryScope,
    PolicyRequest,
    TrustLevel,
    parse_scope,
    parse_trust,
    scope_root,
)
from .skills import frontmatter

VALID_TYPES = {"person", "project", "preference", "fact", "topic", "session"}
VALID_POLARITIES = {"positive", "negative"}


class SignalScores(TypedDict):
    lexical: float
    vector: float
    entity: float
    time: float


class MemorySearchResult(TypedDict):
    """Stable public search contract, including every configured signal."""

    title: str
    snippet: str
    zone: str
    related: list[str]
    score: float
    signal_scores: SignalScores
    source: list[str]
    backend: dict[str, str]
    scope: str
    record_source: str
    trust: str
    shared_read_only: bool

# Per-slug write locks: two channel threads can write the same note concurrently
# (the gateway runs LLM turns outside its global lock), so serialize a note's
# read->check->write to stop lost updates / interleaved corruption.
_NOTE_LOCKS: dict[str, threading.RLock] = {}
_NOTE_LOCKS_GUARD = threading.Lock()


def _note_lock(slug: str) -> threading.RLock:
    with _NOTE_LOCKS_GUARD:
        lk = _NOTE_LOCKS.get(slug)
        if lk is None:
            lk = _NOTE_LOCKS[slug] = threading.RLock()
        return lk


class VersionMismatchError(ValueError):
    """Raised by write_note when expected_version does not match the on-disk
    version (optimistic concurrency control — no stale-snapshot overwrites)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VaultMemory:
    def __init__(self, cfg: dict[str, Any] | None = None, *,
                 embedding_backend: Any | None = None):
        self.cfg = cfg or {}
        self.vault = config.vault_dir(self.cfg)
        self.policy = MemoryAccessPolicy.from_config(self.cfg)
        self._dexes: dict[MemoryScope, Mnemosyne] = {}
        self._embedding_backend = embedding_backend

    def _dex_for(self, scope: MemoryScope) -> Mnemosyne:
        dex = self._dexes.get(scope)
        if dex is None:
            dex = self._dexes[scope] = Mnemosyne(scope_root(self.vault, scope))
        return dex

    @property
    def dex(self) -> Mnemosyne:
        """Mechanical engine for the actor's owning scope (legacy: user)."""
        return self._dex_for(self.policy.actor_scope)

    # -- low-level note IO -------------------------------------------------

    def _resolve_path(self, title: str, note_type: str = "topic",
                      zone: str | None = None,
                      scope: MemoryScope | None = None) -> Path:
        """Existing notes stay where they live; new notes are placed by the
        explicit ``zone`` or the mechanical type→zone map (Morpheus refines
        placement nightly via memory_rezone)."""
        owner = scope or self.policy.actor_scope
        root = scope_root(self.vault, owner)
        s = _slug(title)
        rel = self._dex_for(owner).resolve_rel(s)
        if rel:
            return root / rel
        if zone is not None:
            z = "" if zone in ("", "inbox") else _slug(zone)[:32]
        else:
            z = TYPE_ZONE.get(note_type, "knowledge")
        return (root / z / f"{s}.md") if z else root / f"{s}.md"

    def _find_note(self, title: str,
                   scope: MemoryScope) -> Path | None:
        rel = self._dex_for(scope).resolve_rel(_slug(title))
        root = scope_root(self.vault, scope)
        if rel and (root / rel).is_file():
            return root / rel
        return None

    @staticmethod
    def _record_source(meta: dict[str, Any]) -> str:
        explicit = str(meta.get("record_source") or "")
        raw_sources = meta.get("sources")
        if explicit:
            return explicit
        if isinstance(raw_sources, list) and raw_sources:
            return str(raw_sources[-1])
        return "legacy"

    def get_note_record(self, title: str, *, scope: str | MemoryScope | None = None
                        ) -> dict[str, Any] | None:
        scopes = (parse_scope(scope),) if scope is not None \
            else self.policy.readable_scopes()
        for owner in scopes:
            self.policy.require(PolicyRequest(MemoryOperation.READ, owner))
            p = self._find_note(title, owner)
            if p is None:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, _ = frontmatter.parse(text)
            source = self._record_source(meta)
            self._dex_for(owner).record_access(p.stem)
            return {"content": text, "scope": owner.value,
                    "record_source": source,
                    "trust": self.policy.trust_for(source).value,
                    "shared_read_only": bool(meta.get("shared_read_only", False)),
                    "path": p}
        return None

    def get_note(self, title: str) -> str | None:
        record = self.get_note_record(title)
        return str(record["content"]) if record is not None else None

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
                "path": scope_root(self.vault, self.policy.actor_scope) / entry["rel"],
            })
        return notes

    def profiles_enabled(self) -> bool:
        profile = self.cfg.get("profile")
        return isinstance(profile, dict) and profile.get("enabled") is True

    def profile_actions(self) -> ProfileActions:
        profile = self.cfg.get("profile") if isinstance(self.cfg.get("profile"), dict) else {}
        limits = profile.get("limits", {}) if isinstance(profile, dict) else {}
        return ProfileActions(
            ProfileStore(config.birkin_home(), limits),
            approval_required=bool(profile.get("write_approval", False)) if isinstance(profile, dict) else False,
        )

    def legacy_preferences(self) -> list[LegacyPreference]:
        notes: list[LegacyPreference] = []
        root = scope_root(self.vault, self.policy.actor_scope)
        for entry in self.dex.entries().values():
            path = root / entry["rel"]
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = frontmatter.parse(text)
            try:
                safe_body = validate_profile_text(body)
            except ValueError:
                continue
            notes.append(LegacyPreference(
                path=str(path), title=str(meta.get("title") or entry["title"]),
                body=safe_body, zone=str(entry.get("zone") or ""),
                type=str(meta.get("type") or entry.get("type") or "topic"),
            ))
        return notes

    def archive_legacy_preference(self, note: LegacyPreference) -> None:
        self.dex.rezone(Path(note.path).stem, ARCHIVE_ZONE)

    def restore_legacy_preference(self, note: LegacyPreference) -> None:
        self.write_note(note.title, note.body, note_type=note.type, zone=note.zone)

    def purge_expired(self) -> int:
        """Archive notes whose ``expires_at`` is in the past; return the count.

        Expired notes stay recoverable and remain hidden from search/render.
        Call this from the nightly maintenance routine, not from a read."""
        archived = 0
        for note_slug, entry in self.dex.entries().items():
            if entry["zone"] != ARCHIVE_ZONE and _is_expired(entry):
                try:
                    self.dex.rezone(note_slug, ARCHIVE_ZONE)
                    archived += 1
                except (OSError, ValueError):
                    pass
        return archived

    def write_note(self, title: str, body: str, *, note_type: str | None = None,
                   tags: list[str] | None = None, links: list[str] | None = None,
                   confidence: float | None = None, source: str | None = None,
                   append: bool = False, ttl_days: int | None = None,
                   polarity: str | None = None, zone: str | None = None,
                   expected_version: int | None = None,
                   valid_at: str | None = None,
                   invalid_at: str | None = None,
                   expired_at: str | None = None,
                   supersedes: list[str] | None = None,
                   scope: str | MemoryScope | None = None,
                   shared_read_only: bool | None = None) -> Path:
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
        requested_type = note_type if note_type in VALID_TYPES else None
        # Serialize the read->check->write for this note so concurrent writers
        # can't both pass the version check and clobber each other (lost update),
        # and so the file is never half-written under a reader. Path resolution
        # happens INSIDE the lock: rezone() takes the same lock, so a move can't
        # slip between resolve and write (stale path -> duplicate note).
        note_slug = _slug(title)
        owner = parse_scope(scope) if scope is not None else self.policy.actor_scope
        root = scope_root(self.vault, owner)
        process_lock = root / f".birkin-note-{note_slug}"
        with _note_lock(note_slug), store.file_lock(process_lock):
            p = self._resolve_path(title, requested_type or "topic", zone, owner)
            created = date.today().isoformat()
            sources: list[str] = []
            existing_body = ""
            existing_type = "topic"
            existing_tags: list[str] = []
            existing_confidence = 0.7
            existing_expires_at: str | None = None
            existing_polarity: str | None = None
            existing_version = 0
            existing_valid_at: str | None = None
            existing_invalid_at: str | None = None
            existing_supersedes: list[str] = []
            existing_source = "legacy"
            existing_shared = False
            if p.is_file():
                old = p.read_text(encoding="utf-8", errors="replace")
                meta, old_body = frontmatter.parse(old)
                created = str(meta.get("created", created))
                old_sources = meta.get("sources")
                if isinstance(old_sources, list):
                    sources = [str(s) for s in old_sources]
                old_type = str(meta.get("type") or "")
                if old_type in VALID_TYPES:
                    existing_type = old_type
                old_tags = meta.get("tags")
                if isinstance(old_tags, list):
                    existing_tags = [str(tag) for tag in old_tags]
                try:
                    existing_confidence = float(meta.get("confidence", 0.7))
                except (TypeError, ValueError):
                    existing_confidence = 0.7
                existing_expires_at = str(meta.get("expires_at") or "") or None
                existing_body = old_body.strip()
                existing_polarity = str(meta.get("polarity") or "") or None
                try:
                    existing_version = int(meta.get("version") or 0)
                except (TypeError, ValueError):
                    existing_version = 0
                existing_valid_at = str(meta.get("valid_at") or "") or None
                existing_invalid_at = str(meta.get("invalid_at") or "") or None
                raw_supersedes = meta.get("supersedes")
                if isinstance(raw_supersedes, list):
                    existing_supersedes = [str(value) for value in raw_supersedes]
                existing_source = self._record_source(meta)
                existing_shared = bool(meta.get("shared_read_only", False))

            resolved_shared = (shared_read_only if shared_read_only is not None
                               else existing_shared)
            self.policy.require(PolicyRequest(
                MemoryOperation.WRITE, owner, resolved_shared))
            if expected_version is not None and int(expected_version) != existing_version:
                raise VersionMismatchError(
                    f"expected version {expected_version}, on-disk {existing_version}")

            if source and source not in sources:
                sources.append(source)
            record_source = source or existing_source

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

            # Vault notes outlive the conversation they came from and
            # sync to the user's other devices, so a key pasted into
            # chat must not be remembered verbatim. Same masker as the
            # transcript autosave — this was the higher-value surface
            # and it was the one left uncovered.
            body = transcripts.redact_text(body.strip())
            if append and existing_body:
                body = existing_body + "\n\n" + body

            # Ensure linked notes appear as wikilinks in a Related section.
            links = links or []
            if links:
                related = " · ".join(f"[[{link}]]" for link in links)
                if "## Related" not in body:
                    body += f"\n\n## Related\n{related}"

            resolved_type = requested_type or existing_type
            resolved_tags = tags if tags is not None else existing_tags
            resolved_confidence = (confidence if confidence is not None
                                   else existing_confidence)
            resolved_expired_at = expired_at or existing_expires_at
            if ttl_days is not None:
                resolved_expired_at = None
                if int(ttl_days) > 0:
                    from datetime import timedelta
                    resolved_expired_at = (date.today()
                                           + timedelta(days=int(ttl_days))).isoformat()

            fm = _compose_frontmatter(
                title=title, note_type=resolved_type, created=created,
                updated=_now_iso()[:10], confidence=resolved_confidence,
                sources=sources, tags=resolved_tags,
                expires_at=resolved_expired_at,
                polarity=pol, version=existing_version + 1,
                valid_at=valid_at or existing_valid_at,
                invalid_at=invalid_at or existing_invalid_at,
                supersedes=(supersedes if supersedes is not None
                            else existing_supersedes),
                record_source=record_source,
                trust=self.policy.trust_for(record_source).value,
                shared_read_only=resolved_shared)
            _atomic_write(p, fm + body + "\n")
            owner_dex = self._dex_for(owner)
            owner_dex.note_written(p)
            owner_dex.record_access(_slug(title))   # writing = using
            return p

    def search(self, query: str, limit: int = 8, *,
               since: str | None = None, until: str | None = None,
               as_of: str | None = None,
               now: datetime | None = None,
               min_trust: str | TrustLevel | None = None) -> list[MemorySearchResult]:
        """Search with lexical defaults and explicitly enabled local signals.

        BM25/Hangul ranking is unchanged when all optional signals are off.
        Every result exposes normalized per-signal scores, signal sources, and
        backend names so callers never have to infer why a note was returned.
        """
        from .memory_semantic import (cosine_scores, embedding_backend,
                                      entity_scores, overlaps, parse_day,
                                      validity_score)

        terms = tokenize(query)
        if not terms:
            return []
        minimum = parse_trust(min_trust or TrustLevel.UNTRUSTED)
        effective_day = (parse_day(as_of) or
                         (now or datetime.now(timezone.utc)).date())
        temporal = bool(self.cfg.get("memory_temporal_enabled"))
        readable = self.policy.readable_scopes()
        entries: dict[str, dict[str, Any]] = {}
        owners: dict[str, MemoryScope] = {}
        for owner in readable:
            for item, entry in self._dex_for(owner).entries().items():
                if item not in entries:  # precedence order resolves duplicates
                    entries[item] = entry
                    owners[item] = owner
        entries = {
            item: entry for item, entry in entries.items()
            if self.policy.meets_trust(self._record_source(entry), minimum)
        }
        owners = {item: owner for item, owner in owners.items() if item in entries}
        lexical_raw: dict[str, float] = {}
        for owner in readable:
            lexical_hits = self._dex_for(owner).search(
                query, limit=max(limit, 32), now=now,
                valid_on=(effective_day if temporal or as_of else None))
            for hit in lexical_hits:
                item = str(hit["slug"])
                if owners.get(item) is owner:
                    lexical_raw[item] = float(hit["score"])
        lexical_max = max(lexical_raw.values(), default=0.0) or 1.0
        lexical = {item: value / lexical_max for item, value in lexical_raw.items()}

        vector: dict[str, float] = {}
        vector_backend = None
        if self.cfg.get("memory_vector_enabled"):
            vector_backend = self._embedding_backend
            if vector_backend is None:
                vector_backend = embedding_backend(
                    str(self.cfg.get("memory_vector_backend")
                        or "sentence-transformers"),
                    str(self.cfg.get("memory_vector_model")
                        or "all-MiniLM-L6-v2"))
                self._embedding_backend = vector_backend
            vector = cosine_scores(query, entries, vector_backend)

        entity: dict[str, float] = {}
        if self.cfg.get("memory_entity_enabled"):
            entity = entity_scores(query, entries)

        since_day, until_day = parse_day(since), parse_day(until)
        candidates = set(lexical) | {item for item, value in vector.items() if value} \
            | {item for item, value in entity.items() if value}
        ranked: list[tuple[float, str, SignalScores]] = []
        for item in candidates:
            entry = entries.get(item)
            if entry is None or not overlaps(entry, since_day, until_day):
                continue
            time_score = validity_score(item, entry, entries, effective_day) \
                if temporal or as_of or since or until else 1.0
            if time_score <= 0:
                continue
            scores: SignalScores = {
                "lexical": round(lexical.get(item, 0.0), 6),
                "vector": round(vector.get(item, 0.0), 6),
                "entity": round(entity.get(item, 0.0), 6),
                "time": round(time_score, 6),
            }
            # Optional weights are additive; validity is a gate/multiplier so
            # a superseded fact cannot outrank its current replacement.
            score = scores["lexical"]
            if self.cfg.get("memory_vector_enabled"):
                score += 0.35 * scores["vector"]
            if self.cfg.get("memory_entity_enabled"):
                score += 0.15 * scores["entity"]
            score *= time_score
            ranked.append((score, item, scores))
        ranked.sort(key=lambda row: (row[0], entries[row[1]].get("updated", "")),
                    reverse=True)

        out: list[MemorySearchResult] = []
        for score, item, scores in ranked[:limit]:
            entry = entries[item]
            body = entry["summary"]
            try:
                _, parsed = frontmatter.parse(
                    (scope_root(self.vault, owners[item]) / entry["rel"]).read_text(
                        encoding="utf-8", errors="replace"))
                body = parsed or body
            except OSError:
                pass
            sources = [name for name in ("lexical", "vector", "entity")
                       if scores[name] > 0]
            backends = {"lexical": "mnemosyne-bm25"}
            if scores["vector"] > 0 and vector_backend is not None:
                backends["vector"] = str(vector_backend.name)
            if scores["entity"] > 0:
                backends["entity"] = "wikilink-entity-graph"
            if temporal or as_of or since or until:
                sources.append("time")
                backends["time"] = "validity-v1"
            out.append({"title": item,
                        "snippet": _snippet(body, terms),
                        "zone": entry["zone"] or "inbox",
                        "related": [_slug(t) for t in entry["links"][:3]],
                        "score": round(score, 6),
                        "signal_scores": scores,
                        "source": sources,
                        "backend": backends,
                        "scope": owners[item].value,
                        "record_source": self._record_source(entry),
                        "trust": self.policy.trust_for(
                            self._record_source(entry)).value,
                        "shared_read_only": bool(
                            entry.get("shared_read_only", False))})
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
        with _note_lock(_slug(from_title)):
            record = self.get_note_record(from_title)
            if record is None:
                return False
            text = str(record["content"])
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
                            scope=str(record["scope"]))
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
        lines = [f"Vault searchable historical context: {self.vault} ({total} notes). "
                 f"Use memory_search / memory_get_note for details; role profile files win on conflicts."]
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
                if self.profiles_enabled():
                    receipt = self.profile_actions().submit(
                        ProfileEdit("preferences", "add", content=f"{key}: {value}"),
                        trusted=True, source="remember")
                    return ToolResult(json.dumps(receipt.payload(), sort_keys=True),
                                      is_error=receipt.status == "error")
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
            if self.profiles_enabled() and str(inp.get("type") or "") == "preference":
                return ToolResult(
                    "memory_write_note(type='preference') is disabled while profiles are enabled; use profile_write.",
                    is_error=True)
            try:
                p = self.write_note(
                    title, body,
                    note_type=(str(inp["type"])
                               if inp.get("type") is not None else None),
                    tags=inp.get("tags"),
                    links=inp.get("links") or [],
                    confidence=(float(inp["confidence"])
                                if inp.get("confidence") is not None else None),
                    source=inp.get("source") or "conversation",
                    append=bool(inp.get("append", False)),
                    ttl_days=(int(inp["ttl_days"])
                              if inp.get("ttl_days") is not None else None),
                    polarity=inp.get("polarity"),
                    zone=inp.get("zone"),
                    expected_version=(int(inp["expected_version"])
                                      if inp.get("expected_version") is not None
                                      else None),
                    valid_at=inp.get("valid_at"),
                    invalid_at=inp.get("invalid_at"),
                    expired_at=inp.get("expired_at"),
                    supersedes=inp.get("supersedes"),
                    scope=inp.get("scope"),
                    shared_read_only=(bool(inp["shared_read_only"])
                                      if "shared_read_only" in inp else None))
            except VersionMismatchError as exc:
                return ToolResult(f"write rejected (stale version): {exc}",
                                  is_error=True)
            except MemoryPolicyError as exc:
                return ToolResult(f"write rejected ({type(exc).__name__}): {exc}",
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
                                  limit=int(inp.get("limit", 8)),
                                  since=inp.get("since"), until=inp.get("until"),
                                  as_of=inp.get("as_of"),
                                  min_trust=inp.get("min_trust"))
            if not results:
                return ToolResult("No matching notes.")
            lines = []
            for result in results:
                scores = result["signal_scores"]
                score_text = " ".join(
                    f"{name}={scores[name]:.3f}"
                    for name in ("lexical", "vector", "entity", "time"))
                backend_text = ",".join(
                    f"{name}:{backend}"
                    for name, backend in result["backend"].items())
                lines.append(f"- [[{result['title']}]]: {result['snippet']} "
                             f"[scope={result['scope']}; trust={result['trust']}; "
                             f"record_source={result['record_source']}; "
                             f"{score_text}; backend={backend_text}]")
            return ToolResult("\n".join(lines))

        def memory_get_note(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            text = self.get_note(inp.get("title", ""))
            return (ToolResult(text) if text is not None
                    else ToolResult(f"No note titled {inp.get('title')!r}.",
                                    is_error=True))

        def memory_link(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
            try:
                ok = self.add_link(inp.get("from", ""), inp.get("to", ""))
            except MemoryPolicyError as exc:
                return ToolResult(f"link rejected ({type(exc).__name__}): {exc}",
                                  is_error=True)
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

        tools = [
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
                                          "description": "optimistic-lock check"},
                     "valid_at": {"type": "string", "format": "date"},
                     "invalid_at": {"type": "string", "format": "date"},
                     "expired_at": {"type": "string", "format": "date"},
                     "supersedes": {"type": "array",
                                    "items": {"type": "string"}},
                     "scope": {"type": "string",
                               "enum": [s.value for s in MemoryScope]},
                     "shared_read_only": {"type": "boolean"}},
                     "required": ["title", "body"]},
                 fn=memory_write_note),
            Tool(name="memory_search",
                 description="Keyword-search the semantic memory vault and get "
                             "back matching notes with snippets.",
                 input_schema={"type": "object", "properties": {
                     "query": {"type": "string"},
                     "limit": {"type": "integer"},
                     "since": {"type": "string", "format": "date"},
                     "until": {"type": "string", "format": "date"},
                     "as_of": {"type": "string", "format": "date"},
                     "min_trust": {"type": "string",
                                   "enum": [level.value for level in TrustLevel]}},
                     "required": ["query"]},
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
        if self.profiles_enabled():
            from .profile_actions import build_profile_tools
            tools.extend(build_profile_tools(self.profile_actions()))
        return tools


# -- module helpers --------------------------------------------------------

def _compose_frontmatter(*, title: str, note_type: str, created: str,
                         updated: str, confidence: float,
                         sources: list[str], tags: list[str],
                         expires_at: str | None = None,
                         polarity: str = "positive",
                         version: int = 1,
                         valid_at: str | None = None,
                         invalid_at: str | None = None,
                         supersedes: list[str] | None = None,
                         record_source: str = "legacy",
                         trust: str = "medium",
                         shared_read_only: bool = False) -> str:
    src = ", ".join(f'"{s}"' for s in sources)
    tg = ", ".join(str(t) for t in tags)
    ttl_line = f"expires_at: {expires_at}\n" if expires_at else ""
    temporal_lines = ""
    if valid_at:
        temporal_lines += f"valid_at: {valid_at}\n"
    if invalid_at:
        temporal_lines += f"invalid_at: {invalid_at}\n"
    if supersedes:
        temporal_lines += "supersedes: [" + ", ".join(
            f'"{value}"' for value in supersedes) + "]\n"
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
        f"record_source: {record_source}\n"
        f"trust: {trust}\n"
        f"shared_read_only: {'true' if shared_read_only else 'false'}\n"
        f"tags: [{tg}]\n"
        + ttl_line
        + temporal_lines
        + "---\n\n"
    )


def _is_expired(meta: dict[str, Any]) -> bool:
    """True if ``meta['expires_at']`` is a date strictly in the past."""
    return _entry_expired(meta, date.today())


def memory_activity_line(name: str, content: str) -> str | None:
    """A compact, user-facing line for a memory tool result — so a user can
    SEE what was remembered/recalled (P1-2; doubles as a trust boundary,
    since a poisoned recall is only correctable if it's visible). Returns
    None for non-memory tools."""
    c = content or ""
    if name in ("remember", "memory_write_note"):
        m = re.search(r"\[\[([^\]]+)\]\]", c)
        return f"🧠 remembered [[{m.group(1)}]]" if m else "🧠 remembered a note"
    if name == "memory_search":
        # Count result LINES (each result is one "- [[…]]: snippet" line;
        # snippets have newlines stripped, so a line-start test is exact and
        # robust even if a snippet body itself mentions "- [[").
        n = sum(1 for ln in c.splitlines() if ln.startswith("- [["))
        return f"🧠 recalled {n} note(s)" if n else "🧠 searched memory (0)"
    if name == "memory_get_note":
        return "🧠 opened a note"
    if name == "memory_link":
        return "🧠 linked notes"
    if name == "memory_related":
        return "🧠 found related notes"
    return None


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
    inwin: Counter[str] = Counter()
    best_start, best_end, best_distinct = hits[0][0], hits[0][0] + len(hits[0][1]), 1
    j = 0
    for i, (pos, term) in enumerate(hits):
        inwin[term] += 1
        while hits[j][0] < pos - width:
            inwin[hits[j][1]] -= 1
            if not inwin[hits[j][1]]:
                del inwin[hits[j][1]]
            j += 1
        if len(inwin) > best_distinct:
            # record the window's actual right edge (this hit's END), so the
            # slice includes the boundary term that made it best — the old
            # text[:best_start+width] excluded a hit sitting exactly at +width.
            best_distinct, best_start, best_end = len(inwin), hits[j][0], pos + len(term)
    start = max(0, best_start - width // 8)
    end = max(best_start + width, best_end)
    return text[start:end].replace("\n", " ").strip()


def _title_from(note: str) -> str:
    words = re.sub(r"\s+", " ", note.strip()).split(" ")
    return " ".join(words[:6])[:60] or "Note"


# Backwards-compatible alias used by runtime.py
Memory = VaultMemory
