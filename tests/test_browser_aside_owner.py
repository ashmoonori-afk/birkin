from __future__ import annotations

from collections.abc import Callable, Iterator
from queue import Queue
from threading import Event

from birkin.browser_aside_owner import BrowserOwnerLoop
from birkin.browser_aside_playwright_support import (
    BrowserCommand,
    BrowserCommandKind,
)
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_aside_store import BrowserFrameStore
from birkin.sandbox import NetworkPolicy, SandboxPolicy


class _Page:
    url: str = "https://example.com/"

    def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: float,
    ) -> object:
        del wait_until, timeout
        self.url = url
        return None

    def screenshot(self, **kwargs: object) -> bytes:
        del kwargs
        return b"late-frame"

    def on(
        self,
        event: str,
        handler: Callable[[object], None],
    ) -> None:
        del event, handler

    def close(self) -> None:
        return


class _Clock:
    def __init__(self, values: tuple[float, ...]) -> None:
        self._values: Iterator[float] = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def test_expired_screenshot_never_publishes_late_frame() -> None:
    commands: Queue[BrowserCommand] = Queue()
    navigation_reply: Queue[object] = Queue(maxsize=1)
    close_reply: Queue[object] = Queue(maxsize=1)
    commands.put(BrowserCommand(
        kind=BrowserCommandKind.NAVIGATE,
        value="https://example.com/",
        reply=navigation_reply,
        deadline=5.0,
        cancelled=Event(),
    ))
    commands.put(BrowserCommand(
        kind=BrowserCommandKind.CLOSE,
        value=None,
        reply=close_reply,
        deadline=100.0,
        cancelled=Event(),
    ))
    store = BrowserFrameStore()
    policy = BrowserEgressPolicy(
        policy=SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("example.com",),
        ),
        resolver=lambda _host: ("93.184.216.34",),
    )
    BrowserOwnerLoop(
        session_id="browser-1",
        generation=1,
        policy=policy,
        store=store,
        commands=commands,
        clock=_Clock((0.0, 0.0, 0.0, 6.0, 0.0)),
    ).run(_Page(), RuntimeError)
    assert navigation_reply.empty()
    assert close_reply.get_nowait() is None
    assert store.current() is None
