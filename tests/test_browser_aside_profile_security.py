from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest

from birkin.browser_aside_control import browser_workspace_registry
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_orchestration import BrowserOrchestration
from birkin.browser_aside_playwright import PersistentBrowserRuntime
from birkin.browser_aside_policy import BrowserEgressPolicy
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
        assert _private_mode(tmp_path / "browser-aside") == 0o700
        assert _private_mode(profiles_root) == 0o700
        assert all(_private_mode(path) == 0o700 for path in profiles)

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
