from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from birkin.browser import (
    BrowserPolicyGate,
    BrowserPolicyViolation,
    BrowserSession,
    ConsoleMessage,
    NetworkEvent,
)
from birkin.sandbox import NetworkPolicy, PolicyRequest, SandboxPolicy
from birkin.tools import ToolContext, build_registry


class FakeDriver:
    def __init__(self) -> None:
        self.actions: list[tuple[str, tuple[object, ...]]] = []
        self.guard: Callable[[str], None] | None = None
        self.console = [ConsoleMessage("log", "dashboard ready")]
        self.network = [
            NetworkEvent("request", "GET", "http://127.0.0.1:8787/", None, "document"),
            NetworkEvent("response", "GET", "http://127.0.0.1:8787/", 200, "document"),
        ]
        self.closed = False

    def start(self, request_guard: Callable[[str], None]) -> None:
        self.guard = request_guard

    def navigate(self, url: str) -> str:
        assert self.guard is not None
        self.guard(url)
        self.actions.append(("navigate", (url,)))
        return "Birkin"

    def click(self, selector: str) -> None:
        self.actions.append(("click", (selector,)))

    def fill(self, selector: str, value: str) -> None:
        self.actions.append(("fill", (selector, value)))

    def press(self, selector: str, key: str) -> None:
        self.actions.append(("press", (selector, key)))

    def execute(self, script: str) -> object:
        self.actions.append(("execute", (script,)))
        return {"title": "Birkin"}

    def screenshot(self, path: Path, *, full_page: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-png")
        self.actions.append(("screenshot", (path, full_page)))

    def evidence(self) -> tuple[list[ConsoleMessage], list[NetworkEvent]]:
        return list(self.console), list(self.network)

    def close(self) -> None:
        self.closed = True


def _policy(*hosts: str, writes: tuple[str, ...] = (".",)) -> SandboxPolicy:
    return SandboxPolicy(
        network=NetworkPolicy.ALLOWLIST,
        network_allowlist=hosts,
        write_paths=writes,
    )


def test_actions_map_to_shared_sandbox_policy_requests(tmp_path: Path) -> None:
    class RecordingPolicy:
        def __init__(self) -> None:
            self.requests: list[PolicyRequest] = []

        def require(self, request: PolicyRequest):
            self.requests.append(request)
            return object()

    policy = RecordingPolicy()
    driver = FakeDriver()
    browser = BrowserSession(  # type: ignore[arg-type]
        driver,
        policy,
        tmp_path,
        allow_private_network=True,
    )

    browser.navigate("http://localhost:8787/")
    browser.click("#refresh")
    browser.fill("#query", "status")
    browser.press("#query", "Enter")
    browser.execute("document.title")
    browser.screenshot("artifacts/dashboard.png")
    browser.evidence()
    browser.close()

    assert policy.requests == [
        PolicyRequest(network_hosts=("localhost",)),
        PolicyRequest(),
        PolicyRequest(),
        PolicyRequest(),
        PolicyRequest(),
        PolicyRequest(write_paths=("artifacts/dashboard.png",)),
        PolicyRequest(),
        PolicyRequest(),
    ]


def test_allowed_host_navigates_and_denied_host_fails_closed(tmp_path: Path) -> None:
    driver = FakeDriver()
    browser = BrowserSession(
        driver,
        _policy("127.0.0.1"),
        tmp_path,
        allow_private_network=True,
    )

    assert browser.navigate("http://127.0.0.1:8787/") == "Birkin"
    with pytest.raises(BrowserPolicyViolation, match="not allowlisted"):
        browser.navigate("https://example.com/")

    assert [action for action, _ in driver.actions] == ["navigate"]


def test_legacy_browser_rejects_mixed_public_private_dns_answers() -> None:
    gate = BrowserPolicyGate(
        _policy("mixed.example"),
        resolver=lambda _host: ("93.184.216.34", "127.0.0.1"),
    )

    with pytest.raises(BrowserPolicyViolation, match="non-public"):
        gate.check_navigation("https://mixed.example/")


def test_private_navigation_needs_policy_and_explicit_config() -> None:
    policy = _policy("127.0.0.1")
    denied = BrowserPolicyGate(
        policy,
        resolver=lambda _host: ("127.0.0.1",),
    )
    allowed = BrowserPolicyGate(
        policy,
        allow_private_network=True,
        resolver=lambda _host: ("127.0.0.1",),
    )

    with pytest.raises(BrowserPolicyViolation, match="non-public"):
        denied.check_navigation("http://127.0.0.1:8787/")
    allowed.check_navigation("http://127.0.0.1:8787/")


def test_network_off_denies_navigation_by_default(tmp_path: Path) -> None:
    browser = BrowserSession(FakeDriver(), SandboxPolicy(), tmp_path)

    with pytest.raises(BrowserPolicyViolation, match="network is disabled"):
        browser.navigate("http://localhost:8787/")


def test_driver_subrequests_use_the_same_policy_guard(tmp_path: Path) -> None:
    driver = FakeDriver()
    BrowserSession(driver, _policy("localhost"), tmp_path)

    assert driver.guard is not None
    with pytest.raises(BrowserPolicyViolation, match="cdn.example.com"):
        driver.guard("https://cdn.example.com/app.js")


def test_console_and_network_evidence_is_aggregated(tmp_path: Path) -> None:
    browser = BrowserSession(FakeDriver(), _policy("127.0.0.1"), tmp_path)

    evidence = browser.evidence()

    assert evidence == {
        "console": [{"type": "log", "text": "dashboard ready"}],
        "network": [
            {"kind": "request", "method": "GET", "url": "http://127.0.0.1:8787/", "status": None, "resource_type": "document"},
            {"kind": "response", "method": "GET", "url": "http://127.0.0.1:8787/", "status": 200, "resource_type": "document"},
        ],
    }


def test_screenshot_is_relative_named_artifact_and_policy_scoped(tmp_path: Path) -> None:
    driver = FakeDriver()
    browser = BrowserSession(driver, _policy("localhost", writes=("artifacts",)), tmp_path)

    result = browser.screenshot("artifacts/dashboard.png", full_page=False)

    assert result == tmp_path / "artifacts" / "dashboard.png"
    assert result.read_bytes() == b"fake-png"
    with pytest.raises(BrowserPolicyViolation, match="outside the allowed scope"):
        browser.screenshot("elsewhere/dashboard.png")
    with pytest.raises(BrowserPolicyViolation, match="relative artifact path"):
        browser.screenshot("../escape.png")


def test_browser_tools_register_and_honor_disabled_tool_gate(tmp_path: Path) -> None:
    driver = FakeDriver()
    cfg = {
        "sandbox": {
            "network": "allowlist",
            "network_allowlist": ["localhost"],
            "write_paths": ["."],
        },
        "disabled_tools": ["browser_execute"],
        "browser_allow_private_network": True,
    }
    ctx = ToolContext(cfg=cfg, client=None, cwd=tmp_path, browser_driver=driver)
    registry = build_registry(ctx)

    assert {
        "browser_navigate", "browser_click", "browser_fill", "browser_press",
        "browser_execute", "browser_screenshot", "browser_evidence",
    } - set(registry.names()) == {"browser_execute"}
    denied = registry.execute("browser_execute", {"script": "document.title"})
    navigated = registry.execute("browser_navigate", {"url": "http://localhost:8787/"})

    assert denied.is_error and "disabled by Birkin policy" in str(denied.content)
    assert not navigated.is_error


def test_registry_surfaces_typed_policy_refusal(tmp_path: Path) -> None:
    ctx = ToolContext(
        cfg={"sandbox": {"network": "off", "network_allowlist": [], "write_paths": ["."]}},
        client=None,
        cwd=tmp_path,
        browser_driver=FakeDriver(),
    )

    result = build_registry(ctx).execute(
        "browser_navigate", {"url": "https://example.com/"}
    )

    assert result.is_error
    payload = json.loads(str(result.content))
    assert payload["error"] == "BrowserPolicyViolation"
    assert "network is disabled" in payload["message"]
