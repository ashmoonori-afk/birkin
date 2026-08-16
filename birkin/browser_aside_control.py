"""Control ownership and workspace runtime registry for Browser Aside."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import ClassVar, final

from birkin.browser_aside_service import BrowserAsideService

_ACTOR_KINDS = frozenset({"human", "agent", "tool"})
_SURFACES = frozenset({"web", "agent", "terminal"})


@final
class BrowserControlConflict(RuntimeError):
    code: ClassVar[str] = "control_owner_conflict"


@dataclass(frozen=True, slots=True)
class BrowserControlLease:
    owner_id: str
    owner_kind: str
    epoch: int
    expires_at: float


@dataclass(frozen=True, slots=True)
class BrowserControlAudit:
    kind: str
    previous_owner_id: str
    next_owner_id: str
    epoch: int
    timestamp: float


@final
class BrowserControlAuthority:
    def __init__(
        self,
        clock: Callable[[], float],
        lease_seconds: float = 60.0,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("control lease duration must be positive")
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._lock = RLock()
        self._lease: BrowserControlLease | None = None
        self._epoch = 0
        self._sequence = 0

    def acquire(
        self,
        actor_id: str,
        actor_kind: str,
    ) -> BrowserControlLease:
        self._validate_actor(actor_id, actor_kind)
        with self._lock:
            current = self._active_locked()
            if current is not None:
                if current.owner_id == actor_id:
                    refreshed = BrowserControlLease(
                        current.owner_id,
                        current.owner_kind,
                        current.epoch,
                        self._clock() + self._lease_seconds,
                    )
                    self._lease = refreshed
                    return refreshed
                raise BrowserControlConflict(
                    "browser control is owned by another actor"
                )
            self._epoch += 1
            lease = BrowserControlLease(
                actor_id,
                actor_kind,
                self._epoch,
                self._clock() + self._lease_seconds,
            )
            self._lease = lease
            self._sequence = 0
            return lease

    def authorize(
        self,
        actor_id: str,
        epoch: int,
        sequence: int | None = None,
    ) -> None:
        with self._lock:
            current = self._active_locked()
            if (
                current is None
                or current.owner_id != actor_id
                or current.epoch != epoch
            ):
                raise BrowserControlConflict(
                    "browser control lease is stale or not owned"
                )
            if sequence is not None:
                if sequence <= self._sequence:
                    raise BrowserControlConflict(
                        "browser control sequence is stale"
                    )
                self._sequence = sequence
            self._lease = BrowserControlLease(
                current.owner_id,
                current.owner_kind,
                current.epoch,
                self._clock() + self._lease_seconds,
            )

    def release(self, actor_id: str, epoch: int) -> None:
        with self._lock:
            self.authorize(actor_id, epoch)
            self._lease = None
            self._sequence = 0

    def current(self) -> BrowserControlLease | None:
        with self._lock:
            return self._active_locked()

    def handoff(
        self,
        actor_id: str,
        next_actor_id: str,
        next_actor_kind: str,
    ) -> BrowserControlAudit:
        self._validate_actor(next_actor_id, next_actor_kind)
        with self._lock:
            current = self._active_locked()
            if current is None or current.owner_id != actor_id:
                raise BrowserControlConflict(
                    "only the current owner can hand off browser control"
                )
            self._epoch += 1
            self._lease = BrowserControlLease(
                next_actor_id,
                next_actor_kind,
                self._epoch,
                self._clock() + self._lease_seconds,
            )
            self._sequence = 0
            return BrowserControlAudit(
                kind="browser.control_handoff",
                previous_owner_id=actor_id,
                next_owner_id=next_actor_id,
                epoch=self._epoch,
                timestamp=self._clock(),
            )

    def _active_locked(self) -> BrowserControlLease | None:
        current = self._lease
        if (
            current is not None
            and self._clock() >= current.expires_at
        ):
            self._lease = None
            self._sequence = 0
            return None
        return current

    @staticmethod
    def _validate_actor(actor_id: str, actor_kind: str) -> None:
        if not actor_id or actor_kind not in _ACTOR_KINDS:
            raise ValueError("invalid browser control actor")


@final
class BrowserWorkspaceRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._services: dict[str, BrowserAsideService] = {}

    def resolve(
        self,
        workspace_id: str,
        surface: str,
    ) -> BrowserAsideService:
        if not workspace_id or surface not in _SURFACES:
            raise ValueError("invalid Browser Aside registry key")
        with self._lock:
            service = self._services.get(workspace_id)
            if service is None:
                service = BrowserAsideService(workspace_id)
                self._services[workspace_id] = service
            return service

    def close_all(self) -> None:
        with self._lock:
            services = tuple(self._services.values())
            self._services.clear()
        for service in services:
            _ = service.close()


_REGISTRY = BrowserWorkspaceRegistry()


def browser_control_authority(
    clock: Callable[[], float],
    lease_seconds: float = 60.0,
) -> BrowserControlAuthority:
    return BrowserControlAuthority(clock, lease_seconds)


def browser_workspace_registry() -> BrowserWorkspaceRegistry:
    return _REGISTRY
