"""Hold more than one credential for a provider, and rotate on a 429.

birkin already classifies HTTP 429 as ``rate_limit`` (``llm._kind_for_status``),
already retries it with backoff, and already fails over to a *different*
provider once those retries are spent (``llm.FAILOVER_KINDS``). What it could
not do is hold a second key for the SAME provider -- so an account that
rate-limited burned its retries and then answered from another provider on
another model, when the cheap and correct move was the next key of the same
account.

Exhaustion is per credential and time-boxed by the status that caused it, the
way hermes derives its cooldowns (``agent/credential_pool.py`` ``_exhausted_ttl``):
a 401 is usually a mistyped or rotated key worth retrying soon, a 429 is a quota
window worth waiting out.

Follows the convention ``failover.py`` set for this codebase: a wrapper holding
built clients, never surgery on the live one. There is no runtime state to
snapshot and restore, which is what keeps this small.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from .llm import LLMError

# A second credential fixes a spent quota, a revoked key, or an unpaid account.
# It cannot fix an oversized request, a 5xx, or a dead socket -- rotating on
# those would burn every key in the pool on one bad turn.
ROTATE_KINDS = frozenset({"rate_limit", "auth", "billing"})

_COOLDOWN_BAD_KEY = 300.0      # 401: likely mistyped or rotated; retry soon.
_COOLDOWN_DEFAULT = 3600.0     # 429 and anything else: a window to wait out.


def cooldown_for(status: Optional[int]) -> float:
    """Seconds a credential stays out of the rotation after failing ``status``."""
    return _COOLDOWN_BAD_KEY if status == 401 else _COOLDOWN_DEFAULT


def _clean(keys: Any) -> list[str]:
    """Order-preserving, blank-free, duplicate-free key list.

    A duplicated key is not a second chance: exhausting it once exhausts it.
    """
    out: list[str] = []
    for key in keys or []:
        text = str(key or "").strip()
        if text and text not in out:
            out.append(text)
    return out


class CredentialPool:
    """Ordered credentials, each with its own exhaustion cooldown. Thread-safe."""

    def __init__(self, keys: Any, *,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._keys = _clean(keys)
        self._now = now
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def depth(self) -> int:
        return len(self._keys)

    def _available_locked(self) -> Optional[str]:
        moment = self._now()
        for key in self._keys:
            if self._until.get(key, 0.0) <= moment:
                return key
        return None

    def current(self) -> Optional[str]:
        """The credential to use now, or ``None`` while every one is cooling."""
        with self._lock:
            return self._available_locked()

    def mark_exhausted(self, key: str,
                       status: Optional[int] = None) -> Optional[str]:
        """Park ``key`` for its cooldown; return the next usable credential.

        A key the pool does not hold is ignored rather than guessed at: a stale
        rotation must never cost a working credential.
        """
        with self._lock:
            if key in self._keys:
                self._until[key] = self._now() + cooldown_for(status)
            return self._available_locked()


def from_config(cfg: dict[str, Any],
                resolved: Optional[str]) -> Optional[CredentialPool]:
    """A pool for ``cfg["api_keys"]``, or ``None`` when there is nothing to rotate.

    ``resolved`` is the key ``config.get_api_key`` already chose, so it leads the
    rotation: a pool must not silently start a turn on a different account than
    the one the user configured.
    """
    keys = _clean((cfg or {}).get("api_keys"))
    if not keys:
        return None
    lead = str(resolved or "").strip()
    if lead:
        keys = [lead] + [k for k in keys if k != lead]
    if len(keys) < 2:
        return None                       # nothing to rotate to
    return CredentialPool(keys)


class RotatingClient:
    """One ``complete()`` spread over a pool of credentials.

    Retries a rotation-worthy failure on the next credential instead of
    surfacing it, and forwards every other attribute to whichever client is
    answering -- including writes, so a setting changed mid-session survives a
    rotation. ``failover.py`` documents why that matters: a write that reaches
    only one of the wrapped clients vanishes the moment the other takes over.
    """

    _OWN = frozenset({"_pool", "_factory", "_clients", "_active", "_overrides"})

    def __init__(self, pool: CredentialPool,
                 factory: Callable[[str], Any]) -> None:
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_factory", factory)
        object.__setattr__(self, "_clients", {})
        object.__setattr__(self, "_overrides", {})
        object.__setattr__(self, "_active", None)
        key = pool.current()
        if key is not None:
            object.__setattr__(self, "_active", self._client_for(key))

    def _client_for(self, key: str) -> Any:
        client = self._clients.get(key)
        if client is None:
            client = self._factory(key)
            for name, value in self._overrides.items():
                setattr(client, name, value)
            self._clients[key] = client
        return client

    @property
    def active(self) -> Any:
        """The client that would answer right now."""
        return self._active

    @property
    def depth(self) -> int:
        return self._pool.depth

    def __getattr__(self, name: str) -> Any:
        # Only reached for names this wrapper does not define, so provider /
        # model / cli_timeout report whichever credential is answering.
        if name.startswith("__"):
            raise AttributeError(name)
        active = object.__getattribute__(self, "_active")
        if active is None:
            raise AttributeError(name)
        return getattr(active, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in RotatingClient._OWN:
            object.__setattr__(self, name, value)
            return
        # Recorded as well as applied: a client built by a LATER rotation has to
        # start from the same settings, or the write silently expires.
        self._overrides[name] = value
        for client in self._clients.values():
            setattr(client, name, value)

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        last: Optional[LLMError] = None
        while True:
            client = self._active
            if client is None:
                if last is not None:
                    raise last
                raise LLMError(
                    "every credential in the pool is cooling down",
                    kind="rate_limit")
            try:
                return client.complete(**kwargs)
            except LLMError as exc:
                if getattr(exc, "kind", "unknown") not in ROTATE_KINDS:
                    raise
                last = exc
                nxt = self._pool.mark_exhausted(
                    getattr(client, "api_key", ""),
                    getattr(exc, "status", None))
                if nxt is None:
                    raise
                self._active = self._client_for(nxt)
