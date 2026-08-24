"""Sidecar persistence and incremental refresh for the memory index."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

from .atomic import atomic_write
from .index_codec import decode_dynamics, decode_notes
from .index_config import DYNAMICS_FILE, INDEX_FILE, INDEX_VERSION
from .index_types import DynamicsState, NoteEntry, ScanEntry
from .json_types import load_json


def _missing_entry_parser(_path: Path, _rel: str) -> NoteEntry | None:
    raise NotImplementedError


class IndexStore:
    """Incrementally maintained note index with best-effort sidecars."""

    vault: Path
    _lock: threading.RLock
    _notes: dict[str, NoteEntry] | None
    _dyn: DynamicsState | None
    _postings: dict[str, dict[str, int]]
    _avgdl: float
    _entry_parser: Callable[[Path, str], NoteEntry | None] = staticmethod(
        _missing_entry_parser
    )

    def __init__(self, vault: Path) -> None:
        self.vault = Path(vault)
        self._lock = threading.RLock()
        self._notes = None
        self._dyn = None
        self._postings = {}
        self._avgdl = 0.0

    @property
    def _index_path(self) -> Path:
        return self.vault / INDEX_FILE

    @property
    def _dyn_path(self) -> Path:
        return self.vault / DYNAMICS_FILE

    def _load(self) -> None:
        notes: dict[str, NoteEntry] = {}
        try:
            data = load_json(self._index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version") == INDEX_VERSION:
                notes = decode_notes(data.get("notes"))
        except (OSError, json.JSONDecodeError, AttributeError):
            notes = {}
        self._notes = notes
        self._postings = {}
        for note_slug, entry in notes.items():
            self._add_postings(note_slug, entry["terms"])
        self._recompute_avgdl()
        self._load_dynamics()

    def _load_dynamics(self) -> None:
        state: DynamicsState = {"notes": {}, "zones": {}}
        try:
            raw = load_json(self._dyn_path.read_text(encoding="utf-8"))
            state = decode_dynamics(raw)
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        self._dyn = state

    def _save_index(self) -> None:
        try:
            atomic_write(
                self._index_path,
                json.dumps(
                    {"version": INDEX_VERSION, "notes": self._notes},
                    separators=(",", ":"),
                ),
            )
        except OSError:
            pass

    def _save_dynamics(self) -> None:
        try:
            atomic_write(
                self._dyn_path,
                json.dumps(self._dyn, separators=(",", ":")),
            )
        except OSError:
            pass

    def _add_postings(self, note_slug: str, terms: dict[str, int]) -> None:
        for term, frequency in terms.items():
            self._postings.setdefault(term, {})[note_slug] = frequency

    def _drop_postings(self, note_slug: str) -> None:
        entry = (self._notes or {}).get(note_slug)
        for term in entry["terms"] if entry else {}:
            post = self._postings.get(term)
            if post:
                _ = post.pop(note_slug, None)
                if not post:
                    del self._postings[term]

    def _recompute_avgdl(self) -> None:
        notes = self._notes or {}
        total = sum(entry["doclen"] for entry in notes.values())
        self._avgdl = (total / len(notes)) if notes else 0.0

    def _scan(self) -> dict[str, ScanEntry]:
        """Fingerprint root and one-level zone Markdown notes by slug."""
        found: dict[str, ScanEntry] = {}

        def add(name: str, full: str, rel: str) -> None:
            if not name.endswith(".md"):
                return
            try:
                stat = os.stat(full)
            except OSError:
                return
            note_slug = name[:-3]
            current = found.get(note_slug)
            if current is None or stat.st_mtime > current[1]:
                found[note_slug] = (rel, stat.st_mtime, stat.st_size)

        try:
            top = list(os.scandir(self.vault))
        except OSError:
            return found
        for entry in top:
            if entry.name.startswith("."):
                continue
            if entry.is_file():
                add(entry.name, entry.path, entry.name)
            elif entry.is_dir():
                try:
                    children = list(os.scandir(entry.path))
                except OSError:
                    continue
                for child in children:
                    if child.is_file():
                        add(
                            child.name,
                            child.path,
                            f"{entry.name}/{child.name}",
                        )
        return found

    def refresh(self) -> None:
        """Refresh changed files using stat fingerprints."""
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None
            scanned = self._scan()
            changed = False
            for note_slug in [slug for slug in self._notes if slug not in scanned]:
                self._drop_postings(note_slug)
                del self._notes[note_slug]
                changed = True
            for note_slug, (rel, mtime, size) in scanned.items():
                current = self._notes.get(note_slug)
                if (
                    current
                    and current["rel"] == rel
                    and current["mtime"] == mtime
                    and current["size"] == size
                ):
                    continue
                entry = self._entry_parser(self.vault / rel, rel)
                if entry is None:
                    continue
                if current:
                    self._drop_postings(note_slug)
                self._notes[note_slug] = entry
                self._add_postings(note_slug, entry["terms"])
                changed = True
            if changed:
                self._recompute_avgdl()
                self._save_index()

    def _discard_index_cache(self) -> None:
        self._notes = {}
        self._postings = {}

    def note_written(self, path: Path) -> None:
        """Update the index after a caller writes one note file."""
        with self._lock:
            if self._notes is None:
                self._load()
            assert self._notes is not None
            try:
                rel = path.relative_to(self.vault).as_posix()
            except ValueError:
                return
            entry = self._entry_parser(path, rel)
            if entry is None:
                return
            note_slug = path.stem
            if note_slug in self._notes:
                self._drop_postings(note_slug)
            self._notes[note_slug] = entry
            self._add_postings(note_slug, entry["terms"])
            self._recompute_avgdl()
            self._save_index()

    def entries(self) -> dict[str, NoteEntry]:
        """Return a shallow snapshot of all index entries."""
        with self._lock:
            self.refresh()
            return dict(self._notes or {})

    def note_meta(self, note_slug: str) -> NoteEntry | None:
        with self._lock:
            self.refresh()
            entry = (self._notes or {}).get(note_slug)
            return entry.copy() if entry else None

    def resolve_rel(self, note_slug: str) -> str | None:
        with self._lock:
            self.refresh()
            entry = (self._notes or {}).get(note_slug)
            return entry["rel"] if entry else None
