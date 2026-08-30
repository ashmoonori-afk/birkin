"""Fall back to a second model when the primary stops answering.

birkin runs as an always-on daemon (the Telegram gateway, the cron scheduler).
When the primary provider rate-limits, 5xxs past its retries, or the Claude
subscription token expires, every turn returned the same error until a human
noticed. A configured fallback keeps the daemon answering.

The design is a *wrapper*, not surgery on the live client: ``FailoverClient``
holds two fully-built clients and picks one per call. That means there is no
runtime state to snapshot and restore — "back to primary" is just a cooldown
expiring — which replaces a large amount of the machinery hermes needs for the
same behavior.

Enabled by setting ``fallback_provider`` and ``fallback_model`` in config.
"""

from __future__ import annotations

import time
from typing import Any

from .llm import FAILOVER_KINDS, LLMError, LLMStatus

# Attributes that belong to the wrapper itself. Everything else is forwarded to
# the wrapped clients — see __setattr__.
_OWN = frozenset({"primary", "fallback", "cooldown_s", "_down_until"})


class FailoverClient:
    """Two clients, one ``complete()``. Prefers the primary; parks on the
    fallback for ``cooldown_s`` after a failover-worthy error."""

    def __init__(self, primary: Any, fallback: Any, cooldown_s: float = 300.0):
        object.__setattr__(self, "primary", primary)
        object.__setattr__(self, "fallback", fallback)
        object.__setattr__(self, "cooldown_s", float(cooldown_s))
        object.__setattr__(self, "_down_until", 0.0)

    # -- transparency ------------------------------------------------------

    @property
    def active(self) -> Any:
        """The client that would answer right now."""
        return self.fallback if self.on_fallback else self.primary

    @property
    def on_fallback(self) -> bool:
        return time.monotonic() < self._down_until

    def __getattr__(self, name: str) -> Any:
        # Only reached for attributes the wrapper does not define, so reads of
        # provider/model/cli_timeout/... report whichever client is answering.
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "active"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        # Callers configure the live client mid-session (/temperature,
        # cli_access, birkin_mcp, the _status sink). Those writes must reach
        # BOTH clients, or the setting silently vanishes on failover.
        if name in _OWN:
            object.__setattr__(self, name, value)
            return
        setattr(self.primary, name, value)
        setattr(self.fallback, name, value)

    # -- the one behavior --------------------------------------------------

    def _say(self, status: LLMStatus, message: str) -> None:
        sink = getattr(self.primary, "_status", None)
        if sink is not None:
            sink(status)
        else:
            print(f"[birkin] {message}", flush=True)

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        if self.on_fallback:
            return self._via_fallback(**kwargs)
        try:
            result = self.primary.complete(**kwargs)
        except LLMError as exc:
            if getattr(exc, "kind", "unknown") not in FAILOVER_KINDS:
                raise
            self._down_until = time.monotonic() + self.cooldown_s
            self._say(
                LLMStatus(
                    kind="failover",
                    provider=self.primary.provider,
                    model=self.primary.model,
                    reason=exc.kind,
                    retry_in_seconds=int(self.cooldown_s),
                    fallback_provider=self.fallback.provider,
                    fallback_model=self.fallback.model,
                ),
                f"{self.primary.provider} unavailable ({exc.kind}) — "
                f"switching to {self.fallback.provider}/"
                f"{self.fallback.model} for {int(self.cooldown_s)}s",
            )
            return self._via_fallback(**kwargs)
        if self._down_until:            # a probe after the cooldown succeeded
            self._down_until = 0.0
            self._say(
                LLMStatus(
                    kind="recovered",
                    provider=self.primary.provider,
                    model=self.primary.model,
                    reason="primary_recovered",
                ),
                f"{self.primary.provider} recovered — back on "
                f"{self.primary.model}",
            )
        return result

    def _via_fallback(self, **kwargs: Any) -> dict[str, Any]:
        # The caller passes the PRIMARY's model id (Agent holds cfg["model"]).
        # Handing that to a different provider is a guaranteed 404, so the
        # fallback always answers as itself.
        return self.fallback.complete(**{**kwargs, "model": self.fallback.model})
