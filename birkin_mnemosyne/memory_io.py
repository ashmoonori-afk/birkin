"""Vault configuration and note read/write lifecycle."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import frontmatter
from .atomic import atomic_write
from .index_config import ARCHIVE_ZONE, TYPE_ZONE
from .json_types import JsonValue
from .lexical import slug
from .memory_format import compose_frontmatter, is_expired, json_int
from .memory_lock import note_lock
from .memory_types import MemoryNote
from .mnemosyne import Mnemosyne

VALID_TYPES = {"person", "project", "preference", "fact", "topic", "session"}
VALID_POLARITIES = {"positive", "negative"}
MemoryConfig = Mapping[str, JsonValue | os.PathLike[str]]


def now_iso() -> str:
    """Return the current UTC timestamp at frontmatter precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def vault_dir(cfg: MemoryConfig | None) -> Path:
    """Resolve and create the configured vault directory."""
    values = cfg or {}
    raw = values.get("vault_path") or values.get("vault")
    match raw:
        case None | "":
            directory = Path("vault")
        case str() | os.PathLike():
            directory = Path(raw).expanduser()
        case _:
            message = "vault path must be a string"
            raise TypeError(message)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class MemoryIO:
    """Low-level note location, reads, writes, and expiry cleanup."""

    cfg: MemoryConfig
    vault: Path
    _dex: Mnemosyne | None
    _version_error: type[ValueError] = ValueError

    def __init__(self, cfg: MemoryConfig | None = None) -> None:
        self.cfg = cfg or {}
        self.vault = vault_dir(self.cfg)
        self._dex = None

    @property
    def dex(self) -> Mnemosyne:
        """Return the lazily created mechanical index and dynamics engine."""
        if self._dex is None:
            self._dex = Mnemosyne(self.vault)
        return self._dex

    def _resolve_path(
        self,
        title: str,
        note_type: str = "topic",
        zone: str | None = None,
    ) -> Path:
        note_slug = slug(title)
        rel = self.dex.resolve_rel(note_slug)
        if rel:
            return self.vault / rel
        if zone is not None:
            destination_zone = "" if zone in ("", "inbox") else slug(zone)[:32]
        else:
            destination_zone = TYPE_ZONE.get(note_type, "knowledge")
        if destination_zone:
            return self.vault / destination_zone / f"{note_slug}.md"
        return self.vault / f"{note_slug}.md"

    def _find_note(self, title: str) -> Path | None:
        note_slug = slug(title)
        rel = self.dex.resolve_rel(note_slug)
        if rel and (self.vault / rel).is_file():
            return self.vault / rel
        root_note = self.vault / f"{note_slug}.md"
        if root_note.is_file():
            return root_note
        for candidate in self.vault.rglob("*.md"):
            if candidate.stem == note_slug:
                return candidate
        return None

    def get_note(self, title: str) -> str | None:
        path = self._find_note(title)
        if path is None:
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        self.dex.record_access(path.stem)
        return text

    def list_notes(self) -> list[MemoryNote]:
        notes: list[MemoryNote] = []
        for entry in self.dex.entries().values():
            if entry["zone"] == ARCHIVE_ZONE or is_expired(entry):
                continue
            notes.append(
                {
                    "title": entry["title"],
                    "type": entry["type"],
                    "updated": entry["updated"],
                    "confidence": entry["confidence"],
                    "polarity": entry["polarity"],
                    "zone": entry["zone"] or "inbox",
                    "path": self.vault / entry["rel"],
                }
            )
        return notes

    def purge_expired(self) -> int:
        """Delete expired notes and return the number removed."""
        removed = 0
        for path in self.vault.rglob("*.md"):
            try:
                metadata, _body = frontmatter.parse(
                    path.read_text(encoding="utf-8", errors="replace")
                )
            except OSError:
                continue
            if is_expired(metadata):
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    def write_note(
        self,
        title: str,
        body: str,
        *,
        note_type: str = "topic",
        tags: list[str] | None = None,
        links: list[str] | None = None,
        confidence: float = 0.7,
        source: str | None = None,
        append: bool = False,
        ttl_days: int | None = None,
        polarity: str | None = None,
        zone: str | None = None,
        expected_version: int | None = None,
    ) -> Path:
        """Create or update a note under the original memory controls."""
        selected_type = note_type if note_type in VALID_TYPES else "topic"
        note_slug = slug(title)
        with note_lock(note_slug):
            path = self._resolve_path(title, selected_type, zone)
            created = date.today().isoformat()
            sources: list[str] = []
            existing_body = ""
            existing_polarity: str | None = None
            existing_version = 0
            if path.is_file():
                old = path.read_text(encoding="utf-8", errors="replace")
                metadata, old_body = frontmatter.parse(old)
                created = str(metadata.get("created", created))
                old_sources = metadata.get("sources")
                if isinstance(old_sources, list):
                    sources = [str(item) for item in old_sources]
                existing_body = old_body.strip()
                existing_polarity = (
                    str(metadata.get("polarity") or "") or None
                )
                existing_version = json_int(metadata.get("version"), 0)

            if expected_version is not None and expected_version != existing_version:
                message = (
                    f"expected version {expected_version}, "
                    f"on-disk {existing_version}"
                )
                raise self._version_error(message)

            if source and source not in sources:
                sources.append(source)
            if not sources and self.cfg.get("evidence_required"):
                message = (
                    "memory writes require at least one `source` for a new note "
                    "(evidence_required is enabled in config)"
                )
                raise ValueError(message)
            if polarity is not None and polarity not in VALID_POLARITIES:
                message = (
                    f"polarity must be one of {sorted(VALID_POLARITIES)}, "
                    f"got {polarity!r}"
                )
                raise ValueError(message)
            selected_polarity = polarity or existing_polarity or "positive"
            if selected_polarity not in VALID_POLARITIES:
                selected_polarity = "positive"

            normalized_body = body.strip()
            if append and existing_body:
                normalized_body = f"{existing_body}\n\n{normalized_body}"
            note_links = links or []
            if note_links:
                related = " · ".join(f"[[{link}]]" for link in note_links)
                if "## Related" not in normalized_body:
                    normalized_body += f"\n\n## Related\n{related}"

            expires_at = None
            if ttl_days is not None and ttl_days > 0:
                expires_at = (date.today() + timedelta(days=ttl_days)).isoformat()
            frontmatter_text = compose_frontmatter(
                title=title,
                note_type=selected_type,
                created=created,
                updated=now_iso()[:10],
                confidence=confidence,
                sources=sources,
                tags=tags or [],
                expires_at=expires_at,
                polarity=selected_polarity,
                version=existing_version + 1,
            )
            atomic_write(path, frontmatter_text + normalized_body + "\n")
            self.dex.note_written(path)
            self.dex.record_access(note_slug)
            return path
