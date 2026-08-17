from __future__ import annotations

import importlib.util
import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from threading import Event as ThreadEvent
from threading import Thread
from typing import NoReturn

import pytest

from birkin.browser_aside_control import browser_workspace_registry
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_orchestration import BrowserOrchestration
from birkin.browser_aside_playwright import PersistentBrowserRuntime
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_profiles import profile_owner_lock
from birkin.browser_playwright import playwright_browser_available

pytestmark = [
    pytest.mark.browser_integration,
    pytest.mark.skipif(
        not (
            os.environ.get("BIRKIN_BROWSER_INTEGRATION") == "1"
            and importlib.util.find_spec("playwright") is not None
            and playwright_browser_available()
        ),
        reason="requires opt-in Playwright Chromium",
    ),
]


def _private_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _assert_private_directory(path: Path, root: Path) -> None:
    if os.name == "nt":
        metadata = path.stat()
        assert path.is_dir()
        assert not (
            metadata.st_file_attributes
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
        assert path.resolve().is_relative_to(root.resolve())
        return
    assert _private_mode(path) == 0o700


def _runtime(
    *,
    session_id: str,
    generation: int,
    profile: Path,
) -> PersistentBrowserRuntime:
    policy = BrowserEgressPolicy()
    orchestration = BrowserOrchestration(
        session_id=session_id,
        workspace_session_id="test-workspace",
        generation=generation,
        browser_root=profile.parent,
        policy=policy,
    )
    return PersistentBrowserRuntime(
        session_id=session_id,
        generation=generation,
        profile_dir=profile,
        policy=policy,
        requests=orchestration.requests,
    )


def test_workspace_profiles_and_artifacts_are_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    registry = browser_workspace_registry()
    first = registry.resolve("profile-a", "web")
    second = registry.resolve("profile-b", "agent")
    first_status: dict[str, object]
    second_status: dict[str, object]
    try:
        first_status, _ = first.start()
        second_status, _ = second.start()
        profiles_root = tmp_path / "browser-aside" / "profiles"
        profiles = sorted(
            path
            for path in profiles_root.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )
        assert len(profiles) == 2
        assert all(path.parent == profiles_root for path in profiles)
        _assert_private_directory(tmp_path / "browser-aside", tmp_path)
        _assert_private_directory(profiles_root, tmp_path)
        for profile in profiles:
            _assert_private_directory(profile, tmp_path)

        serialized = repr((first_status, second_status))
        assert str(tmp_path) not in serialized
        assert "profile" not in first_status
        assert (
            first_status["browser_session_id"]
            != second_status["browser_session_id"]
        )
    finally:
        _ = first.close()
        _ = second.close()


def test_profile_lock_rejects_overlap_and_recovers_after_close(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "shared-profile"
    first = _runtime(
        session_id="lock-first",
        generation=1,
        profile=profile,
    )
    try:
        with pytest.raises(BrowserAsideError) as captured:
            _ = _runtime(
                session_id="lock-second",
                generation=2,
                profile=profile,
            )
        assert captured.value.code == "browser_profile_locked"
    finally:
        first.close()

    recovered = _runtime(
        session_id="lock-recovered",
        generation=3,
        profile=profile,
    )
    recovered.close()


def test_start_failure_releases_profile_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin import browser_aside_playwright as runtime_module

    profile = tmp_path / "failed-start-profile"
    constructor_returned = ThreadEvent()
    allow_cleanup = ThreadEvent()
    owner_exited = ThreadEvent()
    errors: Queue[str] = Queue(maxsize=1)
    real_event = ThreadEvent
    real_profile_owner_lock = profile_owner_lock
    event_count = 0

    class ControlledReady:
        def __init__(self) -> None:
            self._event: ThreadEvent = real_event()

        def is_set(self) -> bool:
            return self._event.is_set()

        def set(self) -> None:
            self._event.set()
            assert constructor_returned.wait(5)
            assert allow_cleanup.wait(5)

        def wait(self, timeout: float | None = None) -> bool:
            return self._event.wait(timeout)

    def event_factory() -> ThreadEvent | ControlledReady:
        nonlocal event_count
        event_count += 1
        return ControlledReady() if event_count == 1 else real_event()

    @contextmanager
    def observed_profile_lock(path: Path) -> Generator[None]:
        try:
            with real_profile_owner_lock(path):
                yield
        finally:
            owner_exited.set()

    def fail_launch(*_args: object, **_kwargs: object) -> NoReturn:
        raise BrowserAsideError(
            "sentinel_startup_failure",
            "Sentinel startup failure.",
            503,
        )

    def start_runtime() -> None:
        try:
            _ = _runtime(
                session_id="failed-start",
                generation=1,
                profile=profile,
            )
        except BrowserAsideError as exc:
            errors.put(exc.code)
        finally:
            constructor_returned.set()

    monkeypatch.setattr(runtime_module, "Event", event_factory)
    monkeypatch.setattr(
        runtime_module,
        "profile_owner_lock",
        observed_profile_lock,
    )
    monkeypatch.setattr(
        runtime_module,
        "launch_isolated_context",
        fail_launch,
    )
    caller = Thread(target=start_runtime)
    caller.start()
    try:
        assert errors.get(timeout=5) == "sentinel_startup_failure"
        with real_profile_owner_lock(profile):
            pass
    finally:
        allow_cleanup.set()
        caller.join(timeout=5)
        assert not caller.is_alive()
        assert owner_exited.wait(5)
