from __future__ import annotations

import importlib.util
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import cast

import pytest
from typing_extensions import override

from birkin.browser import BrowserSession
from birkin.browser_contracts import BrowserPolicyViolation
from birkin.browser_playwright import PlaywrightDriver, playwright_browser_available
from birkin.sandbox import NetworkPolicy, SandboxPolicy

pytestmark = pytest.mark.browser_integration


def _browser_ready() -> bool:
    return (
        os.environ.get("BIRKIN_BROWSER_INTEGRATION") == "1"
        and importlib.util.find_spec("playwright") is not None
        and playwright_browser_available()
    )

_BROWSER_READY = _browser_ready()


@pytest.mark.skipif(
    not _BROWSER_READY,
    reason="set BIRKIN_BROWSER_INTEGRATION=1 and install Playwright Chromium",
)
def test_real_browser_drives_a_data_page_and_closes(tmp_path: Path) -> None:
    driver = PlaywrightDriver(headless=True)
    browser = BrowserSession(
        driver,
        SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("localhost",),
            write_paths=(".",),
        ),
        tmp_path,
    )
    try:
        # No network is needed for page setup; interaction is still real Chromium.
        _ = browser.execute(
            "document.body.innerHTML = '<button id=go>Go</button>'"
        )
        browser.click("#go")
        shot = browser.screenshot("real-browser.png")
        assert shot.is_file() and shot.stat().st_size > 0
    finally:
        browser.close()


@pytest.mark.skipif(
    not _BROWSER_READY,
    reason="set BIRKIN_BROWSER_INTEGRATION=1 and install Playwright Chromium",
)
def test_real_browser_reaches_private_allowlist_through_proxy(
    tmp_path: Path,
) -> None:
    requested = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            _ = self.wfile.write(b"<title>Proxy proof</title>")

        @override
        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    browser = BrowserSession(
        PlaywrightDriver(headless=True),
        SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("127.0.0.1",),
        ),
        tmp_path,
        allow_private_network=True,
    )
    try:
        url = f"http://127.0.0.1:{server.server_port}/"

        assert browser.navigate(url) == url
        assert requested.is_set()
    finally:
        browser.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.skipif(
    not _BROWSER_READY,
    reason="set BIRKIN_BROWSER_INTEGRATION=1 and install Playwright Chromium",
)
def test_real_browser_reports_proxy_time_dns_rebinding(
    tmp_path: Path,
) -> None:
    answers = iter(
        (
            ("93.184.216.34",),
            ("93.184.216.34",),
            ("127.0.0.1",),
        )
    )
    browser = BrowserSession(
        PlaywrightDriver(headless=True),
        SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("rebind.test",),
        ),
        tmp_path,
        resolver=lambda _host: next(answers, ("127.0.0.1",)),
    )
    try:
        with pytest.raises(
            BrowserPolicyViolation,
            match="DNS answer changed",
        ):
            _ = browser.navigate("http://rebind.test/")
    finally:
        browser.close()


@pytest.mark.skipif(
    not _BROWSER_READY,
    reason="set BIRKIN_BROWSER_INTEGRATION=1 and install Playwright Chromium",
)
def test_real_browser_blocks_non_proxied_webrtc_udp(
    tmp_path: Path,
) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.setblocking(False)
    address = cast(tuple[str, int], listener.getsockname())
    port = address[1]
    browser = BrowserSession(
        PlaywrightDriver(headless=True),
        SandboxPolicy(),
        tmp_path,
    )
    try:
        result = browser.execute(
            """
            (async () => {
              const peer = new RTCPeerConnection({
                iceServers: [{urls: "stun:127.0.0.1:%d"}],
              });
              peer.createDataChannel("policy-probe");
              await peer.setLocalDescription(await peer.createOffer());
              if (peer.iceGatheringState !== "complete") {
                await new Promise(resolve => {
                  peer.addEventListener("icegatheringstatechange", () => {
                    if (peer.iceGatheringState === "complete") resolve();
                  });
                });
              }
              peer.close();
              return "complete";
            })()
            """
            % port
        )

        assert result == "complete"
        with pytest.raises(BlockingIOError):
            _ = listener.recvfrom(65_536)
    finally:
        browser.close()
        listener.close()
