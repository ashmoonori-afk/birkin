from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest


class _Decision(Protocol):
    result: str
    code: str
    approval_id: str | None


class _Operation(Protocol):
    operation_id: str
    generation: int


class _CrashReceipt(Protocol):
    killed_children: tuple[int, ...]
    next_generation: int
    recovered: bool


class _ProfileLease(Protocol):
    path: Path
    generation: int


class _Controller(Protocol):
    def dialog(self, kind: str, source: str) -> _Decision: ...

    def permission(self, kind: str, source: str) -> _Decision: ...

    def open_tab(self) -> int: ...

    def open_popup(self, *, gesture: bool) -> int: ...

    def close_tab(self, tab_id: int) -> None: ...

    def begin(self, operation_id: str, deadline: float) -> _Operation: ...

    def cancel(self, operation: _Operation) -> None: ...

    def complete(self, operation: _Operation, mutation: str) -> bool: ...

    def crash(self, children: tuple[int, ...]) -> _CrashReceipt: ...

    def acquire_profile(
        self,
        workspace_id: str,
        owner_pid: int,
        owner_started_at: float,
    ) -> _ProfileLease: ...

    def attach_personal_profile(self, path: Path) -> None: ...

    def profile_options(self, workspace_id: str) -> dict[str, object]: ...

    def public_snapshot(self) -> dict[str, object]: ...


class _LifecycleModule(Protocol):
    BrowserResourceLimit: type[Exception]
    BrowserProfileLocked: type[Exception]
    BrowserProfileRejected: type[Exception]

    def browser_runtime_controller(
        self,
        root: Path,
        *,
        clock: Callable[[], float],
        process_alive: Callable[[int, float], bool],
        kill_child: Callable[[int], None],
        max_tabs: int,
        max_popups: int,
    ) -> _Controller: ...


def _module() -> _LifecycleModule:
    module: ModuleType = importlib.import_module(
        "birkin.browser_aside_lifecycle"
    )
    return cast(_LifecycleModule, cast(object, module))


def _controller(
    tmp_path: Path,
    *,
    now: list[float] | None = None,
    alive: Callable[[int, float], bool] | None = None,
    killed: list[int] | None = None,
) -> _Controller:
    current = now or [10.0]
    killed_pids = killed if killed is not None else []
    return _module().browser_runtime_controller(
        tmp_path,
        clock=lambda: current[0],
        process_alive=alive or (lambda _pid, _started: False),
        kill_child=killed_pids.append,
        max_tabs=3,
        max_popups=1,
    )


def test_dialog_and_permission_requests_fail_closed(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    for kind in ("alert", "confirm", "prompt", "beforeunload"):
        decision = controller.dialog(kind, "agent")
        assert (decision.result, decision.approval_id) == ("dismissed", None)
    for kind in ("clipboard-read", "camera", "microphone", "geolocation"):
        decision = controller.permission(kind, "human")
        assert (decision.result, decision.code) == (
            "denied",
            "unsupported_capability",
        )


def test_popup_and_tab_caps_reject_before_allocation(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    assert [controller.open_tab() for _ in range(3)] == [1, 2, 3]
    with pytest.raises(_module().BrowserResourceLimit):
        _ = controller.open_tab()
    assert controller.open_popup(gesture=True) == 1
    with pytest.raises(_module().BrowserResourceLimit):
        _ = controller.open_popup(gesture=True)
    controller.close_tab(2)
    assert controller.open_tab() == 4


def test_cancelled_or_timed_out_operation_cannot_mutate(
    tmp_path: Path,
) -> None:
    now = [10.0]
    controller = _controller(tmp_path, now=now)
    cancelled = controller.begin("cancelled", deadline=20.0)
    controller.cancel(cancelled)
    assert controller.complete(cancelled, "navigate") is False
    timed_out = controller.begin("timed-out", deadline=11.0)
    now[0] = 12.0
    assert controller.complete(timed_out, "download") is False
    assert controller.public_snapshot()["revision"] == 0


def test_crash_kills_only_owned_children_and_recovers_generation(
    tmp_path: Path,
) -> None:
    killed: list[int] = []
    controller = _controller(tmp_path, killed=killed)
    receipt = controller.crash((301, 302))
    assert receipt.killed_children == (301, 302)
    assert killed == [301, 302]
    assert receipt.next_generation == 2
    assert receipt.recovered is True


def test_profile_lock_rejects_live_and_reclaims_stale_owner(
    tmp_path: Path,
) -> None:
    live = {(41, 1.0)}
    controller = _controller(
        tmp_path,
        alive=lambda pid, started: (pid, started) in live,
    )
    first = controller.acquire_profile("workspace", 41, 1.0)
    with pytest.raises(_module().BrowserProfileLocked):
        _ = controller.acquire_profile("workspace", 42, 2.0)
    live.clear()
    second = controller.acquire_profile("workspace", 42, 2.0)
    assert second.path == first.path
    assert second.generation == first.generation + 1


def test_isolated_profile_is_default_and_personal_attach_is_rejected(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    options = controller.profile_options("workspace")
    profile = options["user_data_dir"]
    assert isinstance(profile, Path)
    assert profile.is_relative_to(tmp_path)
    assert options["persistent"] is True
    assert "cdp_endpoint" not in options
    with pytest.raises(_module().BrowserProfileRejected):
        controller.attach_personal_profile(Path.home())


def test_public_state_cannot_leak_profile_data(
    tmp_path: Path,
) -> None:
    snapshot = _controller(tmp_path).public_snapshot()
    encoded = repr(snapshot).lower()
    for forbidden in (
        "cookie",
        "authorization",
        "localstorage",
        "user_data_dir",
        str(tmp_path).lower(),
    ):
        assert forbidden not in encoded
