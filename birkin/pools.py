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
from typing import Any, Callable, Hashable

from . import ledger


class SessionPool:
    def __init__(self, factory: Callable[[Hashable], Any], *,
                 max_sessions: int = 8, idle_ttl: float = 3600.0):
        self._factory = factory
        self._max = max(1, int(max_sessions))
        self._ttl = float(idle_ttl)
        self._lock = threading.Lock()
        self._sessions: dict[Hashable, Any] = {}
        self._last_used: dict[Hashable, float] = {}

    def get(self, key: Hashable) -> Any:
        """Return the warm session for ``key``, creating (and evicting) as
        needed. Creation happens outside the lock — factories spawn processes."""
        with self._lock:
            sess = self._sessions.get(key)
            if sess is not None:
                self._last_used[key] = time.monotonic()
                return sess
            evict = self._pick_lru_locked() if len(self._sessions) >= self._max else None
            victim = self._pop_locked(evict) if evict is not None else None
        if victim is not None:
            self._close(victim, evict, "lru")
        sess = self._factory(key)
        overflow = None
        with self._lock:
            # ponytail: racing threads may double-create; keep the first, close ours
            existing = self._sessions.get(key)
            if existing is not None:
                loser = sess
            else:
                # Re-check capacity under the lock: concurrent creations of
                # DIFFERENT keys each passed the capacity gate above (which
                # released the lock before the factory ran), so max_sessions
                # could be exceeded. Evict an LRU now to hold the cap.
                if len(self._sessions) >= self._max:
                    ek = self._pick_lru_locked()
                    overflow = (ek, self._pop_locked(ek)) if ek is not None else None
                self._sessions[key] = sess
                self._last_used[key] = time.monotonic()
                loser = None
        if overflow is not None and overflow[1] is not None:
            self._close(overflow[1], overflow[0], "lru")
        if loser is not None:
            self._close(loser, key, "race")
            return self.get(key)
        ledger.event("session:open", str(key))
        return sess

    def sweep(self) -> int:
        """Close sessions idle past the TTL; returns how many were evicted."""
        cutoff = time.monotonic() - self._ttl
        with self._lock:
            stale = [k for k, t in self._last_used.items() if t < cutoff]
            victims = [(k, self._pop_locked(k)) for k in stale]
        for key, sess in victims:
            if sess is not None:
                self._close(sess, key, "idle")
        return len(victims)

    def put(self, key: Hashable, sess: Any) -> None:
        """Insert an existing session (tests / adoption); closes any previous."""
        with self._lock:
            old = self._pop_locked(key)
            self._sessions[key] = sess
            self._last_used[key] = time.monotonic()
        if old is not None:
            self._close(old, key, "replaced")

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
        if not self._last_used:
            return None
        return min(self._last_used, key=self._last_used.get)  # type: ignore[arg-type]

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
