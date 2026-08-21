"""Small typed helpers for the optional persistent Playwright adapter."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from queue import Queue
from threading import Event
from types import ModuleType
from typing import cast

from birkin.bundled_browser import ensure_bundled_browser
from birkin.browser_aside_engine import (
    BrowserContext,
    BrowserPage,
    Playwright,
    SyncApi,
)


class BrowserCommandKind(Enum):
    STATUS = "status"
    NAVIGATE = "navigate"
    CLOSE = "close"


@dataclass(slots=True)
class BrowserCommand:
    kind: BrowserCommandKind
    value: str | None
    reply: Queue[object]
    deadline: float
    cancelled: Event


def load_sync_api() -> SyncApi:
    if os.environ.get("BIRKIN_BROWSER_FORCE_UNAVAILABLE") == "1":
        raise ImportError("forced unavailable browser")
    ensure_bundled_browser()
    module: ModuleType = importlib.import_module("playwright.sync_api")
    return cast(SyncApi, cast(object, module))


def block_uninspectable_channels(
    context: BrowserContext,
    page: BrowserPage,
) -> None:
    cdp = context.new_cdp_session(page)
    _ = cdp.send("Network.enable")
    _ = cdp.send(
        "Network.setBlockedURLs",
        {"urls": ["ws://*", "wss://*"]},
    )
    context.add_init_script(
        "Object.defineProperty(globalThis,'WebSocket',"
        + "{value:undefined,configurable:false});"
    )


def launch_isolated_context(
    playwright: Playwright,
    profile_dir: Path,
    proxy_server: str,
    credentials: tuple[str, str],
) -> BrowserContext:
    username, password = credentials
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=True,
        viewport={"width": 1024, "height": 700},
        accept_downloads=False,
        proxy={"server": proxy_server, "username": username,
               "password": password},
        args=["--proxy-bypass-list=<-loopback>",
              "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
        service_workers="block",
        timeout=15_000,
    )
