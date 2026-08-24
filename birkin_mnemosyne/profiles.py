"""Automatic role-profile memory with optional proposal sink persistence."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .json_types import JsonObject, JsonValue, load_json
from .profile_store import (
    PROFILE_DESCRIPTIONS,
    apply_proposal,
    bootstrap,
    profile_path,
    read_profiles,
    vault_lock,
)


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
            with vault_lock(self._vault):
                bootstrap(self._system)

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
        return read_profiles(self._system)

    def _profile_path(self, name: str) -> Path:
        return profile_path(self._system, name)

    def _review_and_save(self, exchange: ProfileExchange) -> None:
        proposals = self._parse_review(self._review(exchange))
        if self._save is not None:
            self._save(proposals)
            return
        with vault_lock(self._vault):
            for proposal in proposals:
                apply_proposal(self._system, proposal)

    @staticmethod
    def _parse_review(raw: str) -> tuple[ProfileProposal, ...]:
        try:
            payload = load_json(raw)
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
    def _parse_proposal(name: str, item: JsonValue) -> ProfileProposal:
        if not isinstance(item, dict):
            raise ProfileReviewError(f"profile '{name}' proposal must be an object")
        allowed = {"action", "content", "old_text"}
        extra = set(item) - allowed
        if extra:
            raise ProfileReviewError(
                f"profile '{name}' proposal has unknown field: {min(extra)}"
            )
        raw_action = item.get("action")
        match raw_action:
            case "add":
                action: ProfileAction = "add"
            case "replace":
                action = "replace"
            case "remove":
                action = "remove"
            case _:
                raise ProfileReviewError(
                    f"profile '{name}' proposal has unknown action"
                )

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
    def _string_field(name: str, item: JsonObject, field: str) -> str:
        value = item.get(field, "")
        if not isinstance(value, str):
            raise ProfileReviewError(
                f"profile '{name}' proposal field '{field}' must be a string"
            )
        return value
