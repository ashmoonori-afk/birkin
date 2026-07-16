"""Warm-resource pools for the daemon/gateway.

``SessionPool`` owns warm :class:`~birkin.claude_session.ClaudeStreamSession`
processes keyed by conversation. It bounds what used to be a grow-forever
dict in the gateway:

- **idle TTL** — a session untouched for ``idle_ttl`` seconds is closed on the
  next :meth:`sweep` (the gateway loop calls it), so long-dead chats stop
  holding a live ``claude`` process.
- **max size** — inserting past ``max_sessions`` evicts the least-recently
  used session first.

Every open/evict is mirrored to the SQLite ledger so the dashboard can see
resource churn. Thread-safe; the pool lock is never held across a session's
own (slow) I/O.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Hashable

from . import ledger


@dataclass(frozen=True, slots=True)
class SessionPoolFullError(RuntimeError):
    max_sessions: int

    def __str__(self) -> str:
        return f"session pool has no idle slot (max {self.max_sessions})"


class SessionPool:
    def __init__(self, factory: Callable[[Hashable], Any], *,
                 max_sessions: int = 8, idle_ttl: float = 3600.0):
        self._factory = factory
        self._max = max(1, int(max_sessions))
        self._ttl = float(idle_ttl)
        self._lock = threading.Lock()
        self._sessions: dict[Hashable, Any] = {}
        self._last_used: dict[Hashable, float] = {}
        self._borrowed: dict[int, tuple[Any, int]] = {}

    def get(self, key: Hashable) -> Any:
        """Return the warm session for ``key``, creating (and evicting) as
        needed. Creation happens outside the lock — factories spawn processes."""
        return self._acquire(key, borrowed=False)

    def borrow(self, key: Hashable) -> Any:
        """Return a session protected from automatic eviction until release."""
        return self._acquire(key, borrowed=True)

    def release(self, key: Hashable, sess: Any) -> None:
        """Release one exact borrowed identity; stale releases are ignored."""
        with self._lock:
            identity = id(sess)
            entry = self._borrowed.get(identity)
            if entry is None or entry[0] is not sess:
                return
            if entry[1] > 1:
                self._borrowed[identity] = (sess, entry[1] - 1)
                return
            del self._borrowed[identity]
            if self._sessions.get(key) is sess:
                self._last_used[key] = time.monotonic()

    def _acquire(self, key: Hashable, *, borrowed: bool) -> Any:
        victim_key = None
        victim = None
        with self._lock:
            existing = self._sessions.get(key)
            if existing is not None:
                self._last_used[key] = time.monotonic()
                if borrowed:
                    self._borrow_locked(existing)
                return existing
            if len(self._sessions) >= self._max:
                victim_key = self._pick_lru_locked()
                if victim_key is None:
                    raise SessionPoolFullError(self._max)
                victim = self._pop_locked(victim_key)
        if victim is not None:
            self._close(victim, victim_key, "lru")

        created = self._factory(key)
        loser = None
        full = False
        with self._lock:
            existing = self._sessions.get(key)
            if existing is not None:
                self._last_used[key] = time.monotonic()
                if borrowed:
                    self._borrow_locked(existing)
                result = existing
                loser = created
            elif len(self._sessions) >= self._max:
                result = None
                loser = created
                full = True
            else:
                self._sessions[key] = created
                self._last_used[key] = time.monotonic()
                if borrowed:
                    self._borrow_locked(created)
                result = created
        if loser is not None:
            self._close(loser, key, "capacity" if full else "race")
        if full:
            raise SessionPoolFullError(self._max)
        if result is created:
            ledger.event("session:open", str(key))
        return result

    def sweep(self) -> int:
        """Close sessions idle past the TTL; returns how many were evicted."""
        cutoff = time.monotonic() - self._ttl
        with self._lock:
            stale = [k for k, t in self._last_used.items()
                     if t < cutoff
                     and not self._is_borrowed_locked(self._sessions[k])]
            victims = [(k, self._pop_locked(k)) for k in stale]
        for key, sess in victims:
            if sess is not None:
                self._close(sess, key, "idle")
        return len(victims)

    def put(self, key: Hashable, sess: Any) -> None:
        """Insert an existing session (tests / adoption); closes any previous."""
        with self._lock:
            if key in self._sessions:
                old_key = key
            elif len(self._sessions) >= self._max:
                old_key = self._pick_lru_locked()
                if old_key is None:
                    raise SessionPoolFullError(self._max)
            else:
                old_key = None
            old = self._pop_locked(old_key)
            self._sessions[key] = sess
            self._last_used[key] = time.monotonic()
        if old is not None:
            self._close(old, old_key, "replaced" if old_key == key else "lru")

    def pop(self, key: Hashable) -> Any | None:
        """Remove without closing (caller owns it) — used for restarts."""
        with self._lock:
            return self._pop_locked(key)

    def clear(self) -> None:
        with self._lock:
            victims = list(self._sessions.items())
            self._sessions.clear()
            self._last_used.clear()
        for key, sess in victims:
            self._close(sess, key, "clear")

    def values(self) -> list[Any]:
        with self._lock:
            return list(self._sessions.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    # -- internals ----------------------------------------------------------

    def _pick_lru_locked(self) -> Hashable | None:
        candidates = (key for key, sess in self._sessions.items()
                      if not self._is_borrowed_locked(sess))
        return min(candidates, key=self._last_used.__getitem__, default=None)

    def _borrow_locked(self, sess: Any) -> None:
        identity = id(sess)
        entry = self._borrowed.get(identity)
        count = entry[1] if entry is not None and entry[0] is sess else 0
        self._borrowed[identity] = (sess, count + 1)

    def _is_borrowed_locked(self, sess: Any) -> bool:
        entry = self._borrowed.get(id(sess))
        return entry is not None and entry[0] is sess and entry[1] > 0

    def _pop_locked(self, key: Hashable | None) -> Any | None:
        if key is None:
            return None
        self._last_used.pop(key, None)
        return self._sessions.pop(key, None)

    @staticmethod
    def _close(sess: Any, key: Hashable, reason: str) -> None:
        ledger.event("session:evict", f"{key} ({reason})")
        try:
            sess.close()
        except Exception:
            pass
