"""Search, linking, duplicate recall, and prompt digest for vault memory."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

from . import frontmatter
from .index_config import ARCHIVE_ZONE, IDENTITY_ZONE, WIKILINK_RE
from .index_types import IndexStats, NoteEntry
from .lexical import slug, tokenize
from .memory_format import is_expired, json_float, snippet
from .memory_io import MemoryIO
from .memory_lock import note_lock
from .memory_types import MemorySearchHit


class MemoryRetrieval(MemoryIO):
    """Ergonomic retrieval, relationship, and digest operations."""

    def search(self, query: str, limit: int = 8) -> list[MemorySearchHit]:
        """Return compatibility hits with snippets from top-ranked files."""
        terms = tokenize(query)
        results: list[MemorySearchHit] = []
        for hit in self.dex.search(query, limit=limit):
            body = hit["summary"]
            try:
                _metadata, parsed = frontmatter.parse(
                    (self.vault / hit["rel"]).read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                )
                body = parsed or body
            except OSError:
                pass
            results.append(
                {
                    "title": hit["slug"],
                    "snippet": snippet(body, terms),
                    "zone": hit["zone"] or "inbox",
                    "related": [slug(title) for title in hit["links"][:3]],
                }
            )
        return results

    def neighbors(self, title: str) -> list[str]:
        """Return outgoing wikilink titles from one note."""
        text = self.get_note(title) or ""
        return sorted(set(WIKILINK_RE.findall(text)))

    def near_duplicates(
        self,
        title: str,
        body: str,
        limit: int = 3,
    ) -> list[tuple[str, float]]:
        """Return token-set cosine candidates from the existing index."""
        new_tokens = set(tokenize(f"{title} {body}"))
        if not new_tokens:
            return []
        own_slug = slug(title)
        entries = self.dex.entries()
        candidates: list[tuple[str, float]] = []
        seen: set[str] = set()
        for hit in self.dex.search(f"{title} {body[:400]}", limit=limit + 2):
            candidate_slug = hit["slug"]
            if candidate_slug == own_slug or candidate_slug in seen:
                continue
            seen.add(candidate_slug)
            entry = entries.get(candidate_slug)
            terms: set[str] = set(entry["terms"]) if entry else set()
            if not terms:
                continue
            similarity = len(new_tokens & terms) / math.sqrt(
                len(new_tokens) * len(terms)
            )
            candidates.append((candidate_slug, round(similarity, 3)))
        candidates.sort(key=lambda item: -item[1])
        return candidates[:limit]

    def add_link(self, from_title: str, to_title: str) -> bool:
        text = self.get_note(from_title)
        if text is None:
            return False
        if f"[[{to_title}]]" in text:
            return True
        metadata, body = frontmatter.parse(text)
        updated_body = body.rstrip()
        if "## Related" in updated_body:
            updated_body += f" · [[{to_title}]]"
        else:
            updated_body += f"\n\n## Related\n[[{to_title}]]"
        _ = self.write_note(
            str(metadata.get("title", from_title)),
            updated_body,
            note_type=str(metadata.get("type", "topic")),
            confidence=json_float(metadata.get("confidence"), 0.7),
        )
        return True

    def rezone(self, title: str, zone: str) -> Path:
        """Move one note to another zone."""
        note_slug = slug(title)
        with note_lock(note_slug):
            return self.dex.rezone(note_slug, zone)

    def reindex(self) -> IndexStats:
        """Force-rebuild the vault index and return its statistics."""
        return self.dex.rebuild()

    def render(self, limit: int = 10) -> str:
        """Render the zone-aware, priority-ordered prompt digest."""
        index = self.dex
        now = datetime.now(timezone.utc)
        by_zone: dict[str, list[tuple[float, NoteEntry]]] = {}
        for note_slug, entry in index.entries().items():
            if entry["zone"] == ARCHIVE_ZONE or is_expired(entry):
                continue
            by_zone.setdefault(entry["zone"], []).append(
                (index.effective_of(note_slug, now), entry)
            )
        if not by_zone:
            return ""
        priorities = index.zone_priorities(today=now.date())
        middle = sorted(
            (
                zone
                for zone in by_zone
                if zone not in ("", IDENTITY_ZONE)
            ),
            key=lambda zone: (-priorities.get(zone, 0.0), zone),
        )
        order = (
            ([IDENTITY_ZONE] if IDENTITY_ZONE in by_zone else [])
            + middle
            + ([""] if "" in by_zone else [])
        )
        total = sum(len(entries) for entries in by_zone.values())
        lines = [f"Vault: {self.vault} ({total} notes). Use memory_search / memory_get_note for details."]
        left = limit
        for zone in order:
            if left <= 0:
                break
            group = sorted(
                by_zone[zone],
                key=lambda item: (item[0], item[1]["updated"]),
                reverse=True,
            )
            cap = min(left, 5) if zone == IDENTITY_ZONE else left
            lines.append(f"[{zone or 'inbox'}]")
            for _strength, entry in group[:cap]:
                warning = (
                    " ⚠ known failure — re-verify"
                    if entry["polarity"] == "negative"
                    else ""
                )
                lines.append(
                    f"- [[{entry['title']}]] ({entry['type']}){warning}: {entry['summary']}"
                )
                left -= 1
                if left <= 0:
                    break
        return "\n".join(lines)
