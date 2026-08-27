"""Policy-gated browser QA tools backed by an optional driver."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Protocol, cast, final, runtime_checkable

from birkin.browser_contracts import (
    BrowserError,
    BrowserPolicyViolation,
    BrowserUnavailableError,
    ConsoleMessage,
    NetworkEvent,
)
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_policy import BrowserPolicyGate

from .sandbox import PolicyRequest, SandboxPolicy, SandboxViolation, load_repo_sandbox
from .tools._types import Tool, ToolContext, ToolResult


@runtime_checkable
class BrowserDriver(Protocol):
    def start(self, policy: BrowserEgressPolicy) -> None: ...
    def navigate(self, url: str) -> str: ...
    def click(self, selector: str) -> None: ...
    def fill(self, selector: str, value: str) -> None: ...
    def press(self, selector: str, key: str) -> None: ...
    def execute(self, script: str) -> object: ...
    def screenshot(self, path: Path, *, full_page: bool) -> None: ...
    def evidence(self) -> tuple[list[ConsoleMessage], list[NetworkEvent]]: ...
    def close(self) -> None: ...


@final
class BrowserSession:
    """Stateful browser page whose actions use one immutable SandboxPolicy."""

    def __init__(
        self,
        driver: BrowserDriver,
        policy: SandboxPolicy,
        root: Path,
        *,
        allow_private_network: bool = False,
        resolver: Callable[[str], tuple[str, ...]] | None = None,
    ):
        self._driver = driver
        self._policy = policy
        self._gate = BrowserPolicyGate(
            policy,
            allow_private_network,
            resolver,
        )
        self._egress_policy = BrowserEgressPolicy(
            policy=policy,
            resolver=resolver,
            allow_private_network=allow_private_network,
        )
        self._root = root.resolve()
        self._closed = False
        driver.start(self._egress_policy)

    def _require(self, request: PolicyRequest) -> None:
        try:
            _ = self._policy.require(request)
        except SandboxViolation as exc:
            raise BrowserPolicyViolation(str(exc)) from exc

    def _action(self) -> None:
        if self._closed:
            raise BrowserError("browser session is closed")
        self._require(PolicyRequest())

    def navigate(self, url: str) -> str:
        if self._closed:
            raise BrowserError("browser session is closed")
        self._gate.check_navigation(url)
        try:
            return self._driver.navigate(url)
        except BrowserAsideError as exc:
            raise BrowserPolicyViolation(exc.message) from exc

    def click(self, selector: str) -> None:
        self._action()
        self._driver.click(selector)

    def fill(self, selector: str, value: str) -> None:
        self._action()
        self._driver.fill(selector, value)

    def press(self, selector: str, key: str) -> None:
        self._action()
        self._driver.press(selector, key)

    def execute(self, script: str) -> object:
        self._action()
        return self._driver.execute(script)

    def screenshot(self, name: str, *, full_page: bool = True) -> Path:
        if self._closed:
            raise BrowserError("browser session is closed")
        normalized = name.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if (not name or relative.is_absolute() or ".." in relative.parts
                or Path(name).is_absolute()):
            raise BrowserPolicyViolation(
                f"screenshot requires a relative artifact path: {name!r}"
            )
        self._require(PolicyRequest(write_paths=(str(relative),)))
        target = (self._root / Path(*relative.parts)).resolve()
        if target != self._root and self._root not in target.parents:
            raise BrowserPolicyViolation(
                f"screenshot artifact escapes workspace: {name!r}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        self._driver.screenshot(target, full_page=full_page)
        return target

    def evidence(self) -> dict[str, list[dict[str, object]]]:
        self._action()
        console, network = self._driver.evidence()
        return {
            "console": [asdict(message) for message in console],
            "network": [asdict(event) for event in network],
        }

    def close(self) -> None:
        if not self._closed:
            self._require(PolicyRequest())
            self._driver.close()
            self._closed = True


def _session(ctx: ToolContext) -> BrowserSession:
    current = cast(object, ctx.browser_session)
    if isinstance(current, BrowserSession):
        return current
    candidate = cast(object, ctx.browser_driver)
    driver: BrowserDriver
    if candidate is None:
        try:
            from .browser_playwright import PlaywrightDriver

            driver = PlaywrightDriver()
        except (ImportError, BrowserUnavailableError) as exc:
            raise BrowserUnavailableError(
                "Browser QA requires `pip install birkin[browser]` and "
                + "`python -m playwright install chromium`."
            ) from exc
    elif isinstance(candidate, BrowserDriver):
        driver = candidate
    else:
        raise TypeError("browser_driver does not satisfy BrowserDriver")
    cfg = cast(dict[str, object], cast(object, ctx.cfg))
    defaults = cfg.get("sandbox", {})
    sandbox_defaults = (
        cast(dict[str, object], defaults)
        if isinstance(defaults, dict)
        else None
    )
    spec = load_repo_sandbox(
        ctx.cwd,
        sandbox_defaults,
    )
    current = BrowserSession(
        driver,
        spec.policy,
        ctx.cwd,
        allow_private_network=(
            cfg.get("browser_allow_private_network") is True
        ),
    )
    ctx.browser_session = current
    return current


def _ok(value: object = None) -> ToolResult:
    return ToolResult(
        "ok"
        if value is None
        else json.dumps(value, ensure_ascii=False)
    )


def _run(
    action: str,
    inp: dict[str, object],
    ctx: ToolContext,
) -> ToolResult:
    try:
        browser = _session(ctx)
        if action == "navigate":
            return _ok({"title": browser.navigate(str(inp.get("url", "")))})
        if action == "click":
            browser.click(str(inp.get("selector", "")))
            return _ok()
        if action == "fill":
            browser.fill(str(inp.get("selector", "")), str(inp.get("value", "")))
            return _ok()
        if action == "press":
            browser.press(str(inp.get("selector", "")), str(inp.get("key", "")))
            return _ok()
        if action == "execute":
            return _ok({"result": browser.execute(str(inp.get("script", "")))})
        if action == "screenshot":
            path = browser.screenshot(
                str(inp.get("path", "")), full_page=inp.get("full_page", True) is True
            )
            return _ok({"path": str(path)})
        if action == "evidence":
            return _ok(browser.evidence())
        if action == "close":
            browser.close()
            return _ok()
        raise AssertionError(f"unhandled browser action: {action}")
    except BrowserPolicyViolation as exc:
        return ToolResult(json.dumps({
            "error": type(exc).__name__, "message": str(exc)
        }), is_error=True)


def _tool(
    name: str,
    description: str,
    properties: Mapping[str, object],
    required: list[str],
) -> Tool:
    action = name.removeprefix("browser_")

    def invoke(
        inp: dict[str, object],
        ctx: ToolContext,
    ) -> ToolResult:
        return _run(action, inp, ctx)

    return Tool(name, description, {
        "type": "object", "properties": properties, "required": required,
        "additionalProperties": False,
    }, invoke)


def tools() -> list[Tool]:
    selector: dict[str, object] = {
        "selector": {"type": "string"}
    }
    return [
        _tool("browser_navigate", "Navigate the QA browser to an allowlisted HTTP(S) URL.", {"url": {"type": "string"}}, ["url"]),
        _tool("browser_click", "Click a selector on the current page.", selector, ["selector"]),
        _tool("browser_fill", "Fill a selector with text.", {**selector, "value": {"type": "string"}}, ["selector", "value"]),
        _tool("browser_press", "Press a key on a selector.", {**selector, "key": {"type": "string"}}, ["selector", "key"]),
        _tool("browser_execute", "Execute JavaScript in the current page.", {"script": {"type": "string"}}, ["script"]),
        _tool("browser_screenshot", "Save a PNG under a policy-allowed relative artifact path.", {"path": {"type": "string"}, "full_page": {"type": "boolean", "default": True}}, ["path"]),
        _tool("browser_evidence", "Read aggregated console and network request/response evidence.", {}, []),
        _tool("browser_close", "Close the browser and all owned contexts.", {}, []),
    ]
