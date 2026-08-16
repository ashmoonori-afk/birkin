"""Playwright owner-thread command loop with absolute deadlines."""

from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
from time import monotonic
from typing import final

from birkin.browser_aside_engine import BrowserPage, BrowserRuntimeStatus
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_playwright_support import (
    BrowserCommand,
    BrowserCommandKind,
)
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_store import (
    BrowserFrameStore,
    FrameBlob,
    FrameStoreError,
)


@final
class BrowserOwnerLoop:
    def __init__(
        self,
        *,
        session_id: str,
        generation: int,
        policy: BrowserEgressPolicy,
        store: BrowserFrameStore,
        commands: Queue[BrowserCommand],
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._session_id = session_id
        self._generation = generation
        self._policy = policy
        self._store = store
        self._commands = commands
        self._clock = clock

    def run(
        self,
        page: BrowserPage,
        engine_error: type[Exception],
    ) -> None:
        revision = 1
        frame_revision = 0
        display_url = ""
        while True:
            command = self._commands.get()
            if (
                command.cancelled.is_set()
                or self._clock() >= command.deadline
            ):
                command.cancelled.set()
                continue
            try:
                if command.kind is BrowserCommandKind.CLOSE:
                    command.reply.put(None)
                    return
                blob: FrameBlob | None
                if command.kind is BrowserCommandKind.NAVIGATE:
                    navigation_url = command.value
                    if navigation_url is None:
                        raise BrowserAsideError(
                            "invalid_browser_command",
                            "Navigation URL is required.",
                            400,
                        )
                    self._policy.check_navigation(navigation_url)
                    _ = page.goto(
                        navigation_url,
                        wait_until="load",
                        timeout=max(
                            1,
                            min(
                                15_000,
                                int(
                                    (
                                        command.deadline
                                        - self._clock()
                                    )
                                    * 1_000
                                ),
                            ),
                        ),
                    )
                    if (
                        command.cancelled.is_set()
                        or self._clock() >= command.deadline
                    ):
                        continue
                    content = page.screenshot(
                        type="jpeg",
                        quality=82,
                        animations="disabled",
                    )
                    published = self._store.publish_before(
                        content,
                        deadline=command.deadline,
                        clock=self._clock,
                    )
                    if published is None:
                        continue
                    blob, changed = published
                    if changed:
                        frame_revision += 1
                    revision += 1
                    display_url = page.url
                else:
                    blob = self._store.current()
                    if display_url:
                        content = page.screenshot(
                            type="jpeg",
                            quality=82,
                            animations="disabled",
                        )
                        published = self._store.publish_before(
                            content,
                            deadline=command.deadline,
                            clock=self._clock,
                        )
                        if published is None:
                            continue
                        blob, changed = published
                        if changed:
                            frame_revision += 1
                            revision += 1
                if (
                    command.cancelled.is_set()
                    or self._clock() >= command.deadline
                ):
                    continue
                command.reply.put(
                    BrowserRuntimeStatus(
                        browser_session_id=self._session_id,
                        browser_generation=self._generation,
                        browser_revision=revision,
                        frame_revision=frame_revision,
                        display_url=display_url,
                        frame_digest=blob.digest if blob else None,
                        frame_ref=blob.ref if blob else None,
                    )
                )
            except BrowserAsideError as exc:
                command.reply.put(exc)
            except (
                FrameStoreError,
                OSError,
                ValueError,
                engine_error,
            ):
                command.reply.put(BrowserAsideError(
                    "browser_runtime_failed",
                    "Chromium browser operation failed.",
                    502,
                ))


def fail_pending(
    commands: Queue[BrowserCommand],
    error: Exception,
) -> None:
    while True:
        try:
            command = commands.get_nowait()
        except Empty:
            return
        command.reply.put(error)
