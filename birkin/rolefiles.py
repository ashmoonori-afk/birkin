"""Canonical on-disk role-profile file model."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

from .profile_lock import profile_lock

PROFILE_ORDER: tuple[str, ...] = ("mask", "user", "preferences", "workflow", "automation")
DEFAULT_PROFILE_LIMITS: Mapping[str, int] = {
    "mask": 800, "user": 1375, "preferences": 1375, "workflow": 1000, "automation": 800,
}
_DESCRIPTIONS = {
    "mask": "Conversation style and interaction guidance.",
    "user": "User characteristics and stable personal context.",
    "preferences": "User preferences and favored choices.",
    "workflow": "User work process and execution guidance.",
    "automation": "User workflow automation guidance.",
}
@dataclass(frozen=True)
class ProfileDocument:
    """One role-profile document as stored under ``<home>/profile``."""

    name: str
    guidance: str
    entries: tuple[str, ...]
    used: int
    limit: int
    revision: str


@dataclass(frozen=True)
class ProfileSnapshot:
    """Consistent snapshot of all role-profile documents."""

    documents: Mapping[str, ProfileDocument]
    revision: str


@dataclass(frozen=True)
class ProfileEdit:
    """One transactional edit to a role-profile document."""

    target: str
    action: Literal["add", "replace", "remove"]
    old_text: str = ""
    content: str = ""


@dataclass
class ProfileBudgetExceeded(RuntimeError):
    used: int
    limit: int
    required_reduction: int
    revision: str
    entries: tuple[tuple[int, str], ...]


class ProfileRevisionError(RuntimeError):
    """The supplied optimistic revision no longer matches disk."""


class ProfileStore:
    """Read and write canonical role-profile files under one home directory."""

    def __init__(self, home: Path, limits: Mapping[str, int]) -> None:
        """Bind the store to ``home`` using the supplied per-document limits."""
        self.home = Path(home)
        self.root = self.home / "profile"
        merged = dict(DEFAULT_PROFILE_LIMITS)
        merged.update(limits)
        self.limits = {name: int(merged[name]) for name in PROFILE_ORDER}

    def bootstrap(self) -> None:
        """Create any missing profile files without changing existing content."""
        with profile_lock(self.home):
            self.root.mkdir(parents=True, exist_ok=True)
            for name in PROFILE_ORDER:
                path = self._path(name)
                if not path.exists():
                    self._atomic_write(path, self._format(name, ()))

    def snapshot(self) -> ProfileSnapshot:
        """Return a lock-consistent snapshot of all profile documents."""
        with profile_lock(self.home):
            return self._snapshot_unlocked()

    def apply(
        self,
        edit: ProfileEdit,
        *,
        expected_revision: str | None = None,
    ) -> ProfileSnapshot:
        """Apply one edit atomically and return the resulting snapshot."""
        return self.apply_batch((edit,), expected_revision=expected_revision)

    def apply_batch(
        self,
        edits: Sequence[ProfileEdit],
        *,
        expected_revision: str | None = None,
    ) -> ProfileSnapshot:
        """Apply a batch of edits as one optimistic transaction."""
        with profile_lock(self.home):
            self.bootstrap()
            before = self._snapshot_unlocked()
            if expected_revision is not None and before.revision != expected_revision:
                raise ProfileRevisionError("profile revision changed")
            next_entries = {
                name: list(before.documents[name].entries) for name in PROFILE_ORDER
            }
            for edit in edits:
                self._validate_edit(edit)
                entries = next_entries[edit.target]
                if edit.action == "add":
                    content = _normalize(edit.content)
                    if content in entries:
                        continue
                    entries.append(content)
                    self._check_budget(edit.target, tuple(entries), before.documents[edit.target])
                elif edit.action == "replace":
                    old = _normalize(edit.old_text)
                    if old in entries:
                        new = _normalize(edit.content)
                        index = entries.index(old)
                        if new in entries:
                            entries.pop(index)
                        else:
                            entries[index] = new
                elif edit.action == "remove":
                    old = _normalize(edit.old_text)
                    if old in entries:
                        entries.remove(old)
            for name in PROFILE_ORDER:
                current = before.documents[name].entries
                changed = tuple(next_entries[name])
                if changed != current:
                    self._atomic_write(self._path(name), self._format(name, changed))
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> ProfileSnapshot:
        self.root.mkdir(parents=True, exist_ok=True)
        documents = {name: self._read_document(name) for name in PROFILE_ORDER}
        revision = _hash("\n".join(documents[name].revision for name in PROFILE_ORDER))
        return ProfileSnapshot(documents=documents, revision=revision)

    def _read_document(self, name: str) -> ProfileDocument:
        path = self._path(name)
        if not path.exists():
            text = self._format(name, ())
        else:
            text = path.read_text(encoding="utf-8")
        entries = _entries(text)
        guidance = "\n".join(entries)
        used = _used(entries)
        return ProfileDocument(
            name=name,
            guidance=guidance,
            entries=entries,
            used=used,
            limit=self.limits[name],
            revision=_hash(self._format(name, entries)),
        )

    def _check_budget(
        self,
        name: str,
        entries: tuple[str, ...],
        before: ProfileDocument,
    ) -> None:
        used = _used(entries)
        limit = self.limits[name]
        if used <= limit:
            return
        raise ProfileBudgetExceeded(
            used=before.used,
            limit=limit,
            required_reduction=used - limit,
            revision=before.revision,
            entries=tuple(enumerate(before.entries, 1)),
        )

    def _validate_edit(self, edit: ProfileEdit) -> None:
        if edit.target not in PROFILE_ORDER:
            raise ValueError(f"unknown profile target: {edit.target}")
        if edit.action == "add" and not _normalize(edit.content):
            raise ValueError("add requires content")
        if edit.action == "replace":
            if not _normalize(edit.old_text) or not _normalize(edit.content):
                raise ValueError("replace requires old_text and content")
        if edit.action == "remove" and not _normalize(edit.old_text):
            raise ValueError("remove requires old_text")

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def _format(self, name: str, entries: tuple[str, ...]) -> str:
        body = "".join(f"- {entry}\n" for entry in entries)
        return (
            "---\n"
            f"description: {_DESCRIPTIONS[name]}\n"
            "---\n"
            f"# {name.title()}\n\n"
            "## Guidance\n"
            f"{body}"
        )

    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _entries(text: str) -> tuple[str, ...]:
    _, marker, guidance = text.partition("## Guidance")
    if not marker:
        return ()
    return tuple(
        _normalize(line[2:])
        for line in guidance.splitlines()
        if line.startswith("- ") and _normalize(line[2:])
    )


def _used(entries: tuple[str, ...]) -> int:
    return sum(len(f"- {entry}\n") for entry in entries)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
