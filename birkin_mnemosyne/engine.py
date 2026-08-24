"""Retrieval and zone placement over an indexed, usage-aware vault."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

from .dynamics import STRENGTH_CAP, effective_strength, parse_datetime
from .engine_dynamics import DynamicsEngine
from .index_config import (
    ARCHIVE_ZONE,
    CAND,
    IDENTITY_ZONE,
    MAX_ZONES,
    RELATED_LIMIT,
    RELATED_QUERY_TERMS,
    STALE_DAYS,
    STALE_EFF,
    W_DYN,
    W_ZONE,
    ZONE_RE,
)
from .index_entry import entry_expired
from .index_types import IndexStats, SearchHit, StaleNote
from .lexical import bm25_scores, slug, tokenize


class MemoryEngine(DynamicsEngine):
    """Usage-aware retrieval and placement built on the incremental index."""

    def search(
        self,
        query: str,
        limit: int = 8,
        zone: str | None = None,
        include_archive: bool = False,
        now: datetime | None = None,
    ) -> list[SearchHit]:
        """Search BM25 candidates and rerank by dynamics and zone priority."""
        self.refresh()
        observed_at = now or datetime.now(timezone.utc)
        terms = tokenize(query)
        with self._lock:
            notes = self._notes or {}
            if not terms or not notes:
                return []
            document_lengths = {
                note_slug: entry["doclen"] for note_slug, entry in notes.items()
            }
            base = bm25_scores(
                terms,
                self._postings,
                document_lengths,
                self._avgdl,
                len(notes),
            )
            candidates = sorted(
                base.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:CAND]
            priorities = self.zone_priorities(today=observed_at.date())
            expiry_today = date.today()
            hits: list[SearchHit] = []
            for note_slug, base_score in candidates:
                entry = notes[note_slug]
                if entry_expired(entry, expiry_today):
                    continue
                entry_zone = entry["zone"]
                if zone is not None:
                    if entry_zone != zone:
                        continue
                elif entry_zone == ARCHIVE_ZONE and not include_archive:
                    continue
                strength = effective_strength(
                    self.dynamics_of(note_slug),
                    observed_at,
                )
                score = base_score * (
                    1
                    + W_DYN * strength / STRENGTH_CAP
                    + W_ZONE * priorities.get(entry_zone, 0.0)
                )
                hits.append(
                    {
                        "slug": note_slug,
                        "title": entry["title"],
                        "zone": entry_zone,
                        "rel": entry["rel"],
                        "type": entry["type"],
                        "summary": entry["summary"],
                        "links": entry["links"],
                        "polarity": entry["polarity"],
                        "score": score,
                        "updated": entry["updated"],
                    }
                )
            hits.sort(
                key=lambda hit: (hit["score"], hit["updated"]),
                reverse=True,
            )
            return hits[:limit]

    def related(
        self,
        note_slug: str,
        limit: int = RELATED_LIMIT,
    ) -> list[SearchHit]:
        """Return lexical link candidates excluding known relationships."""
        entry = self.note_meta(note_slug)
        if entry is None:
            return []
        top_terms = [
            term
            for term, _frequency in sorted(
                entry["terms"].items(),
                key=lambda item: item[1],
                reverse=True,
            )[:RELATED_QUERY_TERMS]
        ]
        linked = {slug(title) for title in entry["links"]} | {note_slug}
        hits = self.search(" ".join(top_terms), limit=limit + len(linked))
        return [hit for hit in hits if hit["slug"] not in linked][:limit]

    def stale(self, now: datetime | None = None) -> list[StaleNote]:
        """Return notes past the archive tier, excluding protected zones."""
        observed_at = now or datetime.now(timezone.utc)
        today = observed_at.date()
        stale_notes: list[StaleNote] = []
        for note_slug, entry in self.entries().items():
            if entry["zone"] in (ARCHIVE_ZONE, IDENTITY_ZONE):
                continue
            if entry_expired(entry, today):
                continue
            dynamics = self.dynamics_of(note_slug)
            last_access = parse_datetime(dynamics.get("last_access"))
            if last_access is None:
                continue
            days = (observed_at - last_access).total_seconds() / 86400.0
            strength = effective_strength(dynamics, observed_at)
            if strength < STALE_EFF and days > STALE_DAYS:
                stale_notes.append(
                    {
                        "slug": note_slug,
                        "title": entry["title"],
                        "zone": entry["zone"],
                        "last_access": dynamics.get("last_access", ""),
                        "eff": strength,
                    }
                )
        stale_notes.sort(key=lambda entry: entry["last_access"])
        return stale_notes

    def rezone(self, note_slug: str, zone: str) -> Path:
        """Move a note into another valid one-level zone."""
        destination_zone = "" if zone in ("", "inbox") else str(zone)
        if (
            destination_zone
            and destination_zone != ARCHIVE_ZONE
            and not ZONE_RE.fullmatch(destination_zone)
        ):
            message = f"invalid zone name {zone!r} (want ^[a-z0-9][a-z0-9-]{{0,31}}$)"
            raise ValueError(message)
        with self._lock:
            self.refresh()
            assert self._notes is not None
            entry = self._notes.get(note_slug)
            if entry is None:
                raise ValueError(f"no note with slug {note_slug!r}")
            existing = {
                item["zone"]
                for item in self._notes.values()
                if item["zone"] and item["zone"] != ARCHIVE_ZONE
            }
            if (
                destination_zone
                and destination_zone != ARCHIVE_ZONE
                and destination_zone not in existing
                and len(existing) >= MAX_ZONES
            ):
                raise ValueError(
                    f"zone cap reached ({MAX_ZONES}); re-use an existing zone"
                )
            old = self.vault / entry["rel"]
            new_dir = self.vault / destination_zone if destination_zone else self.vault
            new = new_dir / f"{note_slug}.md"
            if old != new:
                new_dir.mkdir(parents=True, exist_ok=True)
                os.replace(old, new)
            rel = (
                f"{destination_zone}/{note_slug}.md"
                if destination_zone
                else f"{note_slug}.md"
            )
            try:
                stat = new.stat()
                mtime, size = stat.st_mtime, stat.st_size
            except OSError:
                mtime, size = entry["mtime"], entry["size"]
            self._notes[note_slug] = {
                **entry,
                "rel": rel,
                "zone": destination_zone,
                "mtime": mtime,
                "size": size,
            }
            self._save_index()
            return new

    def rebuild(self) -> IndexStats:
        """Discard the index cache, rescan everything, and return stats."""
        with self._lock:
            if self._dyn is None:
                self._load_dynamics()
            self._discard_index_cache()
            self.refresh()
            return self.stats()

    def stats(self) -> IndexStats:
        with self._lock:
            notes = self._notes or {}
            zones = {entry["zone"] or "inbox" for entry in notes.values()}
            return {
                "notes": len(notes),
                "zones": len(zones),
                "terms": len(self._postings),
                "stale": len(self.stale()),
            }
