"""Automatic role-profile memory with optional proposal sink persistence."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .atomic import atomic_write

PROFILE_DESCRIPTIONS = {
    "user": "User characteristics and stable personal context.",
    "preferences": "User preferences and favored choices.",
    "soul": "Conversation style and interaction guidance.",
    "workflow": "User work process and execution guidance.",
    "automation": "User workflow automation guidance.",
}

_PROFILE_TITLES = {
    "user": "User",
    "preferences": "Preferences",
    "soul": "Soul",
    "workflow": "Workflow",
    "automation": "Automation",
}
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _vault_lock(vault: Path) -> threading.Lock:
    key = vault.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


@dataclass(frozen=True)
class ProfileExchange:
    """One conversation exchange submitted for durable profile review."""

    user: str
    assistant: str


class ProfileReviewError(ValueError):
    """The reviewer returned data outside the role-profile contract."""


ProfileReviewer = Callable[[ProfileExchange], str]
ProfileAction = Literal["add", "replace", "remove"]


@dataclass(frozen=True)
class ProfileProposal:
    """One validated role-profile update proposed by a reviewer."""

    profile: str
    action: ProfileAction
    content: str = ""
    old_text: str = ""


ProfileSaver = Callable[[tuple[ProfileProposal, ...]], None]


class ProfileMemory:
    """Review exchanges into role-profile files or an injected proposal sink."""

    def __init__(
        self,
        vault: Path,
        review: ProfileReviewer,
        *,
        save: ProfileSaver | None = None,
    ) -> None:
        self._vault = Path(vault)
        self._system = self._vault / "system"
        self._review = review
        self._save = save
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="mnemosyne-profile-review",
        )
        self._state_lock = threading.Lock()
        self._pending: list[Future[None]] = []
        self._closed = False
        if self._save is None:
            self._bootstrap()

    def __enter__(self) -> "ProfileMemory":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def record_exchange(
        self,
        user: str,
        assistant: str,
    ) -> Future[None]:
        """Queue an exchange for review and return without waiting for it."""
        exchange = ProfileExchange(user=user, assistant=assistant)
        with self._state_lock:
            if self._closed:
                raise RuntimeError("profile memory is closed")
            future = self._executor.submit(self._review_and_save, exchange)
            self._pending.append(future)
            return future

    def flush(self) -> None:
        """Wait for queued reviews and surface any reviewer failure."""
        with self._state_lock:
            pending, self._pending = self._pending, []
        for future in pending:
            future.result()

    def close(self) -> None:
        """Stop accepting exchanges and release the background worker."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        try:
            self.flush()
        finally:
            self._executor.shutdown()

    def read_profiles(self) -> dict[str, list[str]]:
        """Return persisted guidance for each role profile."""
        if self._save is not None:
            raise RuntimeError("profile sink mode owns no files")
        return {
            name: self._read_guidance(self._profile_path(name))
            for name in PROFILE_DESCRIPTIONS
        }

    def _bootstrap(self) -> None:
        with _vault_lock(self._vault):
            self._system.mkdir(parents=True, exist_ok=True)
            for name, description in PROFILE_DESCRIPTIONS.items():
                path = self._profile_path(name)
                if path.exists():
                    continue
                text = (
                    "---\n"
                    f"description: {description}\n"
                    "---\n"
                    f"# {_PROFILE_TITLES[name]}\n\n"
                    "## Guidance\n"
                )
                atomic_write(path, text)

    def _profile_path(self, name: str) -> Path:
        return self._system / f"{name}.md"

    def _review_and_save(self, exchange: ProfileExchange) -> None:
        proposals = self._parse_review(self._review(exchange))
        if self._save is not None:
            self._save(proposals)
            return
        with _vault_lock(self._vault):
            for proposal in proposals:
                self._apply_file_proposal(proposal)

    def _apply_file_proposal(self, proposal: ProfileProposal) -> None:
        path = self._profile_path(proposal.profile)
        current = path.read_text(encoding="utf-8")
        lines = current.splitlines()
        old_line = f"- {proposal.old_text}" if proposal.old_text else ""
        new_line = f"- {proposal.content}" if proposal.content else ""

        if proposal.action == "add":
            if new_line in lines:
                return
            atomic_write(path, f"{current.rstrip()}\n{new_line}\n")
            return

        try:
            index = lines.index(old_line)
        except ValueError:
            return

        if proposal.action == "replace":
            if new_line in lines:
                lines.pop(index)
            else:
                lines[index] = new_line
        elif proposal.action == "remove":
            lines.pop(index)
        atomic_write(path, "\n".join(lines).rstrip() + "\n")

    @staticmethod
    def _parse_review(raw: str) -> tuple[ProfileProposal, ...]:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProfileReviewError("review must be valid JSON") from exc
        if not isinstance(payload, dict) or set(payload) != {"profiles"}:
            raise ProfileReviewError("review must contain only 'profiles'")
        profiles = payload["profiles"]
        if not isinstance(profiles, dict):
            raise ProfileReviewError("'profiles' must be an object")
        unknown = set(profiles) - PROFILE_DESCRIPTIONS.keys()
        if unknown:
            raise ProfileReviewError(f"unknown profile: {min(unknown)}")

        proposals: list[ProfileProposal] = []
        for name, value in profiles.items():
            if isinstance(value, str):
                content = ProfileMemory._normalize_legacy_guidance(name, value)
                proposals.append(
                    ProfileProposal(profile=name, action="add", content=content)
                )
                continue
            if not isinstance(value, list):
                raise ProfileReviewError(
                    f"profile '{name}' guidance must be a string or proposal list"
                )
            for item in value:
                proposals.append(ProfileMemory._parse_proposal(name, item))
        return tuple(proposals)

    @staticmethod
    def _normalize_legacy_guidance(name: str, guidance: str) -> str:
        if not guidance.strip():
            raise ProfileReviewError(
                f"profile '{name}' guidance must be a non-empty string"
            )
        return " ".join(guidance.split())

    @staticmethod
    def _parse_proposal(name: str, item: Any) -> ProfileProposal:
        if not isinstance(item, dict):
            raise ProfileReviewError(f"profile '{name}' proposal must be an object")
        allowed = {"action", "content", "old_text"}
        extra = set(item) - allowed
        if extra:
            raise ProfileReviewError(
                f"profile '{name}' proposal has unknown field: {min(extra)}"
            )
        action = item.get("action")
        if action not in {"add", "replace", "remove"}:
            raise ProfileReviewError(f"profile '{name}' proposal has unknown action")

        content = ProfileMemory._string_field(name, item, "content")
        old_text = ProfileMemory._string_field(name, item, "old_text")
        if action == "add":
            if not content.strip():
                raise ProfileReviewError(
                    f"profile '{name}' add proposal requires content"
                )
            if old_text != "":
                raise ProfileReviewError(
                    f"profile '{name}' add proposal must not include old_text"
                )
        elif action == "replace":
            if not content.strip() or not old_text.strip():
                raise ProfileReviewError(
                    f"profile '{name}' replace proposal requires content and old_text"
                )
        elif action == "remove":
            if content != "":
                raise ProfileReviewError(
                    f"profile '{name}' remove proposal must not include content"
                )
            if not old_text.strip():
                raise ProfileReviewError(
                    f"profile '{name}' remove proposal requires old_text"
                )
        return ProfileProposal(
            profile=name,
            action=action,
            content=content,
            old_text=old_text,
        )

    @staticmethod
    def _string_field(name: str, item: dict[str, Any], field: str) -> str:
        value = item.get(field, "")
        if not isinstance(value, str):
            raise ProfileReviewError(
                f"profile '{name}' proposal field '{field}' must be a string"
            )
        return value

    @staticmethod
    def _read_guidance(path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        _, _, guidance = text.partition("## Guidance")
        return [
            line.removeprefix("- ").strip()
            for line in guidance.splitlines()
            if line.startswith("- ")
        ]
