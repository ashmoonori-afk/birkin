"""Deterministic Browser Aside resource and profile lifecycle."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import final

from birkin.browser_aside_artifacts import (
    ArtifactQuotaExceeded,
    BrowserArtifactStore,
)

__all__ = [
    "ArtifactQuotaExceeded",
    "BrowserArtifactStore",
    "BrowserProfileLocked",
    "BrowserProfileRejected",
    "BrowserResourceLimit",
    "browser_artifact_store",
    "browser_runtime_controller",
    "ensure_private_directory",
]


class BrowserResourceLimit(RuntimeError):
    """A bounded Browser resource limit was reached."""


class BrowserProfileLocked(RuntimeError):
    """A live verified process owns the Browser profile."""


class BrowserProfileRejected(RuntimeError):
    """Attaching a personal or arbitrary profile is prohibited."""


@dataclass(frozen=True, slots=True)
class BrowserDecision:
    result: str
    code: str = ""
    approval_id: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserOperation:
    operation_id: str
    generation: int


@dataclass(frozen=True, slots=True)
class BrowserCrashReceipt:
    killed_children: tuple[int, ...]
    next_generation: int
    recovered: bool


@dataclass(frozen=True, slots=True)
class BrowserProfileLease:
    path: Path
    generation: int
    owner_pid: int
    owner_started_at: float


@dataclass(slots=True)
class _OperationState:
    operation: BrowserOperation
    deadline: float
    cancelled: bool = False


@final
class BrowserRuntimeController:
    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], float],
        process_alive: Callable[[int, float], bool],
        kill_child: Callable[[int], None],
        max_tabs: int,
        max_popups: int,
    ) -> None:
        self._root = root.resolve()
        self._clock = clock
        self._process_alive = process_alive
        self._kill_child = kill_child
        self._max_tabs = max_tabs
        self._max_popups = max_popups
        self._tabs: set[int] = set()
        self._next_tab = 1
        self._popups = 0
        self._generation = 1
        self._revision = 0
        self._operations: dict[str, _OperationState] = {}
        self._profiles: dict[str, BrowserProfileLease] = {}
        self._lock = RLock()
        _ = ensure_private_directory(self._root)

    def dialog(self, kind: str, source: str) -> BrowserDecision:
        del kind, source
        return BrowserDecision("dismissed", "dialog_dismissed")

    def permission(self, kind: str, source: str) -> BrowserDecision:
        del kind, source
        return BrowserDecision("denied", "unsupported_capability")

    def open_tab(self) -> int:
        with self._lock:
            if len(self._tabs) >= self._max_tabs:
                raise BrowserResourceLimit("browser tab limit reached")
            tab_id = self._next_tab
            self._next_tab += 1
            self._tabs.add(tab_id)
            return tab_id

    def open_popup(self, *, gesture: bool) -> int:
        if not gesture:
            raise BrowserResourceLimit("script popup is blocked")
        with self._lock:
            if self._popups >= self._max_popups:
                raise BrowserResourceLimit("browser popup limit reached")
            self._popups += 1
            return self._popups

    def close_tab(self, tab_id: int) -> None:
        with self._lock:
            self._tabs.discard(tab_id)

    def begin(
        self,
        operation_id: str,
        deadline: float,
    ) -> BrowserOperation:
        with self._lock:
            operation = BrowserOperation(
                operation_id,
                self._generation,
            )
            self._operations[operation_id] = _OperationState(
                operation,
                deadline,
            )
            return operation

    def cancel(self, operation: BrowserOperation) -> None:
        with self._lock:
            state = self._operations.get(operation.operation_id)
            if state is not None:
                state.cancelled = True

    def complete(
        self,
        operation: BrowserOperation,
        mutation: str,
    ) -> bool:
        del mutation
        with self._lock:
            state = self._operations.pop(
                operation.operation_id,
                None,
            )
            if (
                state is None
                or state.cancelled
                or state.deadline < self._clock()
                or operation.generation != self._generation
            ):
                return False
            self._revision += 1
            return True

    def crash(self, children: tuple[int, ...]) -> BrowserCrashReceipt:
        for pid in children:
            self._kill_child(pid)
        with self._lock:
            self._generation += 1
            self._operations.clear()
            return BrowserCrashReceipt(
                children,
                self._generation,
                True,
            )

    def acquire_profile(
        self,
        workspace_id: str,
        owner_pid: int,
        owner_started_at: float,
    ) -> BrowserProfileLease:
        with self._lock:
            current = self._profiles.get(workspace_id)
            if current is not None and self._process_alive(
                current.owner_pid,
                current.owner_started_at,
            ):
                raise BrowserProfileLocked("browser profile is live")
            generation = current.generation + 1 if current else 1
            path = self._profile_path(workspace_id)
            lease = BrowserProfileLease(
                path,
                generation,
                owner_pid,
                owner_started_at,
            )
            self._profiles[workspace_id] = lease
            return lease

    def attach_personal_profile(self, path: Path) -> None:
        del path
        raise BrowserProfileRejected(
            "personal browser profiles cannot be attached"
        )

    def profile_options(
        self,
        workspace_id: str,
    ) -> dict[str, object]:
        return {
            "user_data_dir": self._profile_path(workspace_id),
            "persistent": True,
        }

    def public_snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "generation": self._generation,
                "revision": self._revision,
                "tab_count": len(self._tabs),
                "popup_count": self._popups,
            }

    def _profile_path(self, workspace_id: str) -> Path:
        digest = hashlib.sha256(workspace_id.encode()).hexdigest()[:24]
        profile_root = self._root / "profiles"
        _ = ensure_private_directory(profile_root)
        path = profile_root / digest
        _ = ensure_private_directory(path)
        return path


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def browser_runtime_controller(
    root: Path,
    *,
    clock: Callable[[], float],
    process_alive: Callable[[int, float], bool],
    kill_child: Callable[[int], None],
    max_tabs: int,
    max_popups: int,
) -> BrowserRuntimeController:
    return BrowserRuntimeController(
        root,
        clock=clock,
        process_alive=process_alive,
        kill_child=kill_child,
        max_tabs=max_tabs,
        max_popups=max_popups,
    )


def browser_artifact_store(
    root: Path,
    *,
    clock: Callable[[], float],
    retention_seconds: int,
    max_records: int,
    max_bytes: int,
) -> BrowserArtifactStore:
    return BrowserArtifactStore(
        root,
        clock=clock,
        retention_seconds=retention_seconds,
        max_records=max_records,
        max_bytes=max_bytes,
    )
