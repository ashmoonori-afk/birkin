"""Best-effort background extraction for role profiles.

Without a durable outbox, exchanges queued here can be lost on process crash.
Failures are isolated from the user's turn and retained only as bounded session
notices; this is best-effort background extraction, not guaranteed capture.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from threading import RLock
from typing import Any

from birkin_mnemosyne import profiles

from .profile_actions import ProfileActions, ProfileReceipt
from .rolefiles import PROFILE_ORDER, ProfileEdit

UPSTREAM_TO_LOCAL: Mapping[str, str] = {
    "soul": "mask",
    "user": "user",
    "preferences": "preferences",
    "workflow": "workflow",
    "automation": "automation",
}

Complete = Callable[[str], str]


@dataclass(frozen=True)
class _Turn:
    user: str
    assistant: str


class _DoneFuture(Future[None]):
    def __init__(self) -> None:
        super().__init__()
        self.set_result(None)


class ProfileReviewService:
    """Session-scoped adapter around upstream profile parsing/scheduling."""

    def __init__(
        self,
        cfg: Mapping[str, Any],
        actions: ProfileActions,
        complete: Complete,
        *,
        max_pending: int = 64,
    ) -> None:
        self.cfg = cfg
        self.actions = actions
        self.complete = complete
        self.digest_recent_turns = int(cfg.get("digest_recent_turns", 6))
        self._max_pending = max(1, max_pending)
        self._lock = RLock()
        self._history: dict[str, deque[_Turn]] = defaultdict(lambda: deque(maxlen=128))
        self._notices: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=32))
        self._sessions: dict[str, str] = {}
        self._closed = False
        self._current_session = ""
        self._memory = profiles.ProfileMemory(
            actions.store.home,
            self._review,
            save=self._save,
        )

    def record_exchange(
        self,
        user: str,
        assistant: str,
        *,
        trusted: bool,
        session_id: str,
    ) -> Future[None] | None:
        if not trusted or self._closed:
            return None
        sid = str(session_id or "default")
        with self._lock:
            self._history[sid].append(_Turn(user, assistant))
            self._sessions[self._digest(sid)] = sid
            pending = getattr(self._memory, "_pending", [])
            if len(pending) >= self._max_pending:
                self._notice(sid, "profile review skipped: pending queue full")
                return _DoneFuture()
            self._current_session = sid
        upstream = self._memory.record_exchange(self._digest(sid), assistant)
        outer: Future[None] = Future()
        def done(fut: Future[None], session: str = sid) -> None:
            self._capture(session, fut)
            outer.set_result(None)
        upstream.add_done_callback(done)
        return outer

    def drain_notices(self, session_id: str) -> tuple[str, ...]:
        sid = str(session_id or "default")
        with self._lock:
            notices = tuple(self._notices.get(sid, ()))
            self._notices[sid].clear()
            return notices

    def close(self) -> None:
        self._closed = True
        try:
            self._memory.close()
        except Exception as exc:
            self._notice("default", f"profile review failed during close: {exc}")

    def flush(self) -> None:
        try:
            self._memory.flush()
        except Exception as exc:
            self._notice("default", f"profile review failed during flush: {exc}")

    def _review(self, exchange: profiles.ProfileExchange) -> str:
        sid = self._sessions.get(exchange.user, self._current_session or "default")
        prompt = (
            "Extract durable role-profile updates as JSON {'profiles': ...}.\n"
            f"Digest:\n{exchange.user}\n\nAssistant:\n{exchange.assistant}"
        )
        try:
            return self.complete(prompt)
        except Exception as exc:
            self._notice(sid, f"profile review failed: {exc}")
            raise

    def _save(self, proposals: tuple[profiles.ProfileProposal, ...]) -> None:
        sid = self._current_session or "default"
        overflow = False
        for proposal in proposals:
            target = UPSTREAM_TO_LOCAL.get(proposal.profile)
            if target not in PROFILE_ORDER:
                continue
            edit = ProfileEdit(
                target=target,
                action=proposal.action,
                old_text=proposal.old_text,
                content=proposal.content,
            )
            receipt = self.actions.submit(edit, trusted=True, source="review")
            if receipt.status == "error" and (receipt.error or {}).get("type") == "budget_exceeded":
                overflow = True
        if overflow:
            self._repair_once(sid)

    def _repair_once(self, sid: str) -> None:
        prompt = (
            "A profile proposal exceeded budget. Return one compact JSON repair "
            "using replace/remove where possible; do not append blindly.\n"
            f"Current digest:\n{self._digest(sid)}"
        )
        try:
            raw = self.complete(prompt)
            repaired = profiles.ProfileMemory._parse_review(raw)  # upstream contract parser
        except Exception as exc:
            self._notice(sid, f"profile repair failed; proposal left pending: {exc}")
            return
        for proposal in repaired:
            target = UPSTREAM_TO_LOCAL.get(proposal.profile)
            if target not in PROFILE_ORDER:
                continue
            receipt = self.actions.submit(
                ProfileEdit(target, proposal.action, proposal.old_text, proposal.content),
                trusted=True,
                source="review-repair",
            )
            if receipt.status == "error":
                self._stage_pending(target, proposal, receipt)

    def _stage_pending(
        self,
        target: str,
        proposal: profiles.ProfileProposal,
        receipt: ProfileReceipt,
    ) -> None:
        previous = self.actions.approval_required
        self.actions.approval_required = True
        try:
            self.actions.submit(
                ProfileEdit(target, proposal.action, proposal.old_text, proposal.content),
                trusted=True,
                source="review-overflow",
            )
        finally:
            self.actions.approval_required = previous
        self._notice("default", f"profile proposal pending after overflow: {receipt.error}")

    def _digest(self, sid: str) -> str:
        turns = list(self._history[sid])
        keep = max(0, self.digest_recent_turns)
        older = turns[:-keep] if keep else turns
        recent = turns[-keep:] if keep else []
        lines: list[str] = []
        if older:
            lines.append(f"Older summary: {len(older)} earlier turn(s) omitted.")
        for i, turn in enumerate(recent, 1):
            lines.append(f"Recent turn {i} user:\n{turn.user}")
            lines.append(f"Recent turn {i} assistant:\n{turn.assistant}")
        return "\n\n".join(lines)

    def _capture(self, sid: str, future: Future[None]) -> None:
        try:
            future.result()
        except Exception as exc:
            self._notice(sid, f"profile review failed: {exc}")

    def _notice(self, sid: str, notice: str) -> None:
        with self._lock:
            self._notices[str(sid or "default")].append(notice)


def build_profile_review(
    cfg: Mapping[str, Any],
    actions: ProfileActions,
    complete: Complete,
) -> ProfileReviewService | None:
    """Build the auxiliary reviewer, never falling back to the main model."""
    profile_cfg = cfg.get("profile", cfg)
    review = profile_cfg.get("background_review", {}) if isinstance(profile_cfg, Mapping) else {}
    if not isinstance(review, Mapping) or not review.get("enabled", False):
        return None
    if not review.get("provider") or not review.get("model"):
        return None
    return ProfileReviewService(review, actions, complete)
