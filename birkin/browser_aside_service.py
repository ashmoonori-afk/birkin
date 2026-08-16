"""UI-independent lifecycle service for Native Browser Aside."""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import final
from urllib.parse import urlsplit, urlunsplit

from birkin.browser_aside_engine import BrowserRuntimeStatus
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_lifecycle import ensure_private_directory
from birkin.browser_aside_orchestration import BrowserOrchestration
from birkin.browser_aside_playwright import PersistentBrowserRuntime
from birkin.browser_aside_policy import (
    BrowserEgressPolicy,
    private_network_rules,
)
from birkin.browser_aside_profiles import (
    clear_profile_lock,
    purge_stale_profiles,
)
from birkin.browser_aside_store import FrameBlob
from birkin.config import birkin_home
from birkin.sandbox import load_repo_sandbox


@final
class BrowserAsideService:
    """Own exactly one persistent isolated Browser Aside runtime."""

    def __init__(self, workspace_id: str = "standalone") -> None:
        self._workspace_id = workspace_id
        self._lock = RLock()
        self._runtime: PersistentBrowserRuntime | None = None
        self._orchestration: BrowserOrchestration | None = None
        self._profile_dir: Path | None = None
        self._generation = 0
        self._event_cursor = 0

    def start(
        self,
        *,
        actor_id: str = "human:web",
        control_epoch: int = 1,
    ) -> tuple[dict[str, object], bool]:
        with self._lock:
            if self._runtime is not None:
                if self._orchestration is not None:
                    self._orchestration.update_authority(
                        actor_id,
                        control_epoch,
                    )
                return self._status_payload(self._runtime.status()), False
            session_id = uuid.uuid4().hex
            self._generation += 1
            browser_root = ensure_private_directory(
                birkin_home() / "browser-aside"
            )
            profiles = ensure_private_directory(browser_root / "profiles")
            _ = purge_stale_profiles(profiles)
            profile = profiles / session_id
            private_rules = private_network_rules(
                os.environ.get(
                    "BIRKIN_BROWSER_PRIVATE_NETWORK_RULES",
                    "",
                )
            )
            defaults: dict[str, object] | None = None
            if private_rules:
                defaults = {
                    "network": "allowlist",
                    "network_allowlist": sorted({
                        host for host, _, _ in private_rules
                    }),
                }
            sandbox = load_repo_sandbox(Path.cwd(), defaults)
            control_addresses = tuple(
                address.strip()
                for address in os.environ.get(
                    "BIRKIN_BROWSER_CONTROL_ADDRESSES",
                    "",
                ).split(",")
                if address.strip()
            )
            policy = BrowserEgressPolicy(
                policy=sandbox.policy,
                private_network=private_rules,
                control_addresses=control_addresses,
            )
            orchestration = BrowserOrchestration(
                session_id=session_id,
                workspace_session_id=self._workspace_id,
                generation=self._generation,
                browser_root=browser_root,
                policy=policy,
                actor_id=actor_id,
                control_epoch=control_epoch,
                event_cursor_start=self._event_cursor,
            )
            runtime = PersistentBrowserRuntime(
                session_id=session_id,
                generation=self._generation,
                profile_dir=profile,
                policy=policy,
                requests=orchestration.requests,
            )
            orchestration.started()
            self._runtime = runtime
            self._orchestration = orchestration
            self._profile_dir = profile
            return self._status_payload(runtime.status()), True

    def status(self) -> dict[str, object]:
        with self._lock:
            if self._runtime is None:
                return {
                    "live": False,
                    "engine": "chromium",
                    "persistent": True,
                    "browser_session_id": None,
                    "browser_generation": self._generation,
                    "browser_revision": 0,
                    "frame_revision": 0,
                    "display_url": "",
                    "frame_digest": None,
                    "frame_ref": None,
                }
            return self._status_payload(self._runtime.status())

    def navigate(
        self,
        url: str,
        *,
        expected_generation: int,
        expected_revision: int,
    ) -> dict[str, object]:
        with self._lock:
            runtime = self._runtime
            orchestration = self._orchestration
            if runtime is None or orchestration is None:
                raise BrowserAsideError(
                    "browser_session_missing",
                    "Open the Browser Aside before navigating.",
                    409,
                )
            current = runtime.status()
            if current.browser_generation != expected_generation:
                raise BrowserAsideError(
                    "stale_browser_generation",
                    "Browser generation is stale.",
                    409,
                )
            if current.browser_revision != expected_revision:
                raise BrowserAsideError(
                    "stale_browser_revision",
                    "Browser revision is stale.",
                    409,
                )
            return self._status_payload(
                orchestration.navigate(runtime, url)
            )

    def frame(
        self,
        *,
        generation: int | None,
    ) -> tuple[FrameBlob, dict[str, object]]:
        with self._lock:
            runtime = self._runtime
            if runtime is None:
                raise BrowserAsideError(
                    "browser_session_missing",
                    "Open the Browser Aside before requesting a frame.",
                    409,
                )
            status = runtime.status()
            if (
                generation is not None
                and generation != status.browser_generation
            ):
                raise BrowserAsideError(
                    "stale_browser_generation",
                    "Requested browser generation is stale.",
                    409,
                )
            frame = runtime.frame()
            if frame is None:
                raise BrowserAsideError(
                    "frame_unavailable",
                    "No browser frame is available yet.",
                    404,
                )
            orchestration = self._orchestration
            if orchestration is not None:
                orchestration.viewport_ready(status, frame)
            return frame, self._status_payload(status)

    def close(self) -> dict[str, object]:
        with self._lock:
            runtime = self._runtime
            if runtime is None:
                return {"closed": False, "cleanup": "already_closed"}
            cleanup_error: BrowserAsideError | None = None
            try:
                runtime.close()
            except BrowserAsideError as exc:
                cleanup_error = exc
            finally:
                self._runtime = None
            profile = self._profile_dir
            if cleanup_error is None and profile is not None:
                try:
                    shutil.rmtree(profile)
                    clear_profile_lock(profile)
                except OSError as exc:
                    cleanup_error = BrowserAsideError(
                        "browser_profile_cleanup_failed",
                        "Browser profile cleanup failed.",
                        500,
                    )
                    del exc
            self._profile_dir = None
            orchestration = self._orchestration
            if orchestration is not None:
                orchestration.stopped(
                    "failed" if cleanup_error else "clean"
                )
                self._event_cursor = orchestration.cursor
            self._orchestration = None
            if cleanup_error is not None:
                raise cleanup_error
            return {"closed": True, "cleanup": "clean"}

    @staticmethod
    def _status_payload(
        status: BrowserRuntimeStatus,
    ) -> dict[str, object]:
        return {
            "live": True,
            "engine": "chromium",
            "persistent": True,
            **asdict(status),
            "display_url": _display_origin(status.display_url),
        }


def _display_origin(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return ""
    host = (
        f"[{parsed.hostname}]"
        if ":" in parsed.hostname
        else parsed.hostname
    )
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, host + port, "/", "", ""))
