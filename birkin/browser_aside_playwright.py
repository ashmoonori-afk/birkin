"""Owner-thread persistent Playwright runtime for Native Browser Aside."""

from __future__ import annotations

from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
from time import monotonic
from typing import cast, final

from birkin.browser_aside_engine import (
    BrowserContext,
    BrowserRuntimeStatus,
    Playwright,
    PlaywrightManager,
)
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_owner import BrowserOwnerLoop, fail_pending
from birkin.browser_aside_playwright_support import (
    BrowserCommand,
    BrowserCommandKind,
    block_uninspectable_channels,
    launch_isolated_context,
    load_sync_api,
)
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_profiles import profile_owner_lock
from birkin.browser_aside_proxy import BrowserFilteringProxy
from birkin.browser_aside_requests import BrowserRequestAuthority
from birkin.browser_aside_store import (
    BrowserFrameStore,
    FrameBlob,
)

START_TIMEOUT_SECONDS = COMMAND_TIMEOUT_SECONDS = 20
CLOSE_TIMEOUT_SECONDS = 30
QUEUE_CAPACITY = 32


@final
class PersistentBrowserRuntime:
    """Serialize every Playwright operation on one owned thread."""

    def __init__(
        self,
        *,
        session_id: str,
        generation: int,
        profile_dir: Path,
        policy: BrowserEgressPolicy,
        requests: BrowserRequestAuthority,
    ) -> None:
        self._session_id = session_id
        self._generation = generation
        self._profile_dir = profile_dir
        self._policy = policy
        self._requests = requests
        self._store = BrowserFrameStore()
        self._commands: Queue[BrowserCommand] = Queue(maxsize=QUEUE_CAPACITY)
        self._ready = Event()
        self._startup_cancelled = Event()
        self._startup_error: BrowserAsideError | None = None
        self._terminal_error: BrowserAsideError | None = None
        self._thread = Thread(
            target=self._run,
            name=f"birkin-browser-{session_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(START_TIMEOUT_SECONDS):
            self._startup_cancelled.set()
            self._commands.put(BrowserCommand(
                kind=BrowserCommandKind.CLOSE,
                value=None,
                reply=Queue(maxsize=1),
                deadline=float("inf"),
                cancelled=Event(),
            ))
            raise BrowserAsideError(
                "browser_start_timeout",
                "Chromium did not start within the deadline.",
                504,
            )
        if self._startup_error is not None:
            raise self._startup_error

    def status(self) -> BrowserRuntimeStatus:
        return cast(
            BrowserRuntimeStatus,
            self._call(BrowserCommandKind.STATUS),
        )

    def navigate(self, url: str) -> BrowserRuntimeStatus:
        return cast(
            BrowserRuntimeStatus,
            self._call(BrowserCommandKind.NAVIGATE, url),
        )

    def frame(self) -> FrameBlob | None:
        return self._store.current()

    def close(self) -> None:
        if not self._thread.is_alive():
            self._store.clear()
            return
        _ = self._call(BrowserCommandKind.CLOSE)
        self._thread.join(CLOSE_TIMEOUT_SECONDS)
        if self._thread.is_alive():
            raise BrowserAsideError(
                "browser_cleanup_timeout",
                "Chromium cleanup did not finish within the deadline.",
                500,
            )
        if self._terminal_error is not None:
            raise self._terminal_error

    def _call(
        self,
        kind: BrowserCommandKind,
        value: str | None = None,
    ) -> object:
        if not self._thread.is_alive():
            raise self._terminal_error or BrowserAsideError(
                "browser_crashed",
                "Chromium runtime stopped unexpectedly.",
                503,
            )
        reply: Queue[object] = Queue(maxsize=1)
        cancelled = Event()
        deadline = monotonic() + COMMAND_TIMEOUT_SECONDS
        try:
            self._commands.put(
                BrowserCommand(
                    kind=kind,
                    value=value,
                    reply=reply,
                    deadline=deadline,
                    cancelled=cancelled,
                ),
                timeout=1,
            )
        except Full as exc:
            raise BrowserAsideError(
                "browser_backpressure",
                "Browser command queue is full.",
                429,
            ) from exc
        try:
            result = reply.get(
                timeout=max(0.0, deadline - monotonic())
            )
        except Empty as exc:
            cancelled.set()
            raise BrowserAsideError(
                "browser_command_timeout",
                "Browser command exceeded its deadline.",
                504,
            ) from exc
        if isinstance(result, BaseException):
            raise result
        return result

    def _run(self) -> None:
        try:
            api = load_sync_api()
        except ImportError:
            self._startup_error = BrowserAsideError(
                "browser_unavailable",
                "Install the optional browser dependency and Chromium with "
                + "`uv sync --extra browser && "
                + "uv run playwright install chromium`.",
                503,
            )
            self._ready.set()
            return
        manager: PlaywrightManager | None = None
        playwright: Playwright | None = None
        context: BrowserContext | None = None
        proxy: BrowserFilteringProxy | None = None
        profile_lock = profile_owner_lock(self._profile_dir)
        try:
            _ = profile_lock.__enter__()
            self._profile_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            proxy = BrowserFilteringProxy(self._policy)
            proxy.start()
            manager = api.sync_playwright()
            playwright = manager.start()
            context = launch_isolated_context(
                playwright,
                self._profile_dir,
                proxy.url,
                proxy.credentials,
            )
            page = context.pages[0] if context.pages else context.new_page()
            block_uninspectable_channels(context, page)
            context.clear_permissions()
            context.on("page", self._requests.popup)
            page.on("dialog", self._requests.dialog)
            page.on("download", self._requests.download)
            page.on("filechooser", self._requests.file_chooser)
            context.route("**/*", self._requests.route)
            if self._startup_cancelled.is_set():
                return
            self._ready.set()
            BrowserOwnerLoop(
                session_id=self._session_id,
                generation=self._generation,
                policy=self._policy,
                store=self._store,
                commands=self._commands,
            ).run(page, api.Error)
        except (BrowserAsideError, api.Error, OSError) as exc:
            error = BrowserAsideError(
                exc.code
                if isinstance(exc, BrowserAsideError)
                else (
                    "browser_start_failed"
                    if not self._ready.is_set()
                    else "browser_runtime_failed"
                ),
                exc.message
                if isinstance(exc, BrowserAsideError)
                else (
                    "Chromium could not start."
                    if not self._ready.is_set()
                    else "Chromium runtime failed."
                ),
                exc.status
                if isinstance(exc, BrowserAsideError)
                else (503 if not self._ready.is_set() else 500),
            )
            if not self._ready.is_set():
                self._startup_error = error
                self._ready.set()
            else:
                self._terminal_error = error
                fail_pending(self._commands, error)
            del exc
        finally:
            if context is not None:
                try:
                    context.close()
                except api.Error:
                    self._terminal_error = BrowserAsideError(
                        "browser_cleanup_failed",
                        "Chromium context cleanup failed.",
                        500,
                    )
            if playwright is not None:
                try:
                    playwright.stop()
                except api.Error:
                    self._terminal_error = BrowserAsideError(
                        "browser_cleanup_failed",
                        "Playwright cleanup failed.",
                        500,
                    )
            if proxy is not None:
                try:
                    proxy.close()
                except BrowserAsideError as exc:
                    self._terminal_error = exc
            _ = profile_lock.__exit__(None, None, None)
            self._store.clear()
