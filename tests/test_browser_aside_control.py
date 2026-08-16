from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType
from typing import Protocol, cast

import pytest


class _Lease(Protocol):
    owner_id: str
    owner_kind: str
    epoch: int


class _CodedError(Protocol):
    code: str


class _Audit(Protocol):
    kind: str
    previous_owner_id: str
    next_owner_id: str
    epoch: int


class _Authority(Protocol):
    def acquire(self, actor_id: str, actor_kind: str) -> _Lease: ...

    def handoff(
        self,
        actor_id: str,
        next_actor_id: str,
        next_actor_kind: str,
    ) -> _Audit: ...

    def authorize(
        self,
        actor_id: str,
        epoch: int,
        sequence: int | None = None,
    ) -> None: ...


class _Registry(Protocol):
    def resolve(self, workspace_id: str, surface: str) -> object: ...


class _ControlModule(Protocol):
    BrowserControlConflict: type[Exception]

    def browser_control_authority(
        self,
        clock: Callable[[], float],
        lease_seconds: float = 60.0,
    ) -> _Authority: ...

    def browser_workspace_registry(self) -> _Registry: ...


def _module() -> _ControlModule:
    module: ModuleType = importlib.import_module(
        "birkin.browser_aside_control"
    )
    return cast(_ControlModule, cast(object, module))


def test_control_owner_conflict_is_typed_and_epoch_bound() -> None:
    module = _module()
    authority = module.browser_control_authority(lambda: 10.0)
    lease = authority.acquire("human:web", "human")
    assert (lease.owner_id, lease.owner_kind, lease.epoch) == (
        "human:web",
        "human",
        1,
    )
    with pytest.raises(module.BrowserControlConflict) as captured:
        _ = authority.acquire("agent:tool", "agent")
    error = cast(_CodedError, cast(object, captured.value))
    assert error.code == "control_owner_conflict"
    with pytest.raises(module.BrowserControlConflict):
        authority.authorize("human:web", 0)


def test_explicit_handoff_emits_safe_audit_record() -> None:
    authority = _module().browser_control_authority(lambda: 10.0)
    _ = authority.acquire("human:web", "human")
    audit = authority.handoff("human:web", "agent:tool", "agent")
    assert (
        audit.kind,
        audit.previous_owner_id,
        audit.next_owner_id,
        audit.epoch,
    ) == ("browser.control_handoff", "human:web", "agent:tool", 2)
    authority.authorize("agent:tool", 2)


def test_web_and_agent_resolve_same_workspace_runtime() -> None:
    registry = _module().browser_workspace_registry()
    web = registry.resolve("workspace-1", "web")
    agent = registry.resolve("workspace-1", "agent")
    terminal = registry.resolve("workspace-1", "terminal")
    assert web is agent is terminal
    assert registry.resolve("workspace-2", "web") is not web


def test_control_sequence_and_expiry_reject_stale_clients() -> None:
    now = [10.0]
    module = _module()
    authority = module.browser_control_authority(
        lambda: now[0],
        lease_seconds=5.0,
    )
    lease = authority.acquire("human:web:a", "human")
    authority.authorize("human:web:a", lease.epoch, 1)
    with pytest.raises(module.BrowserControlConflict):
        authority.authorize("human:web:a", lease.epoch, 1)
    now[0] = 16.0
    replacement = authority.acquire("human:web:b", "human")
    assert replacement.epoch == lease.epoch + 1
