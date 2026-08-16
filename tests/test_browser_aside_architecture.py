from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest

from birkin.browser import BrowserPolicyGate

_ROOT = Path(__file__).parents[1]


class _Tab(Protocol):
    tab_id: str
    generation: int


class _Session(Protocol):
    def open_tab(self, url: str) -> _Tab: ...

    def activate(self, tab_id: str) -> None: ...

    def action(
        self,
        tab_id: str,
        generation: int,
        kind: str,
    ) -> None: ...


class _SessionModule(Protocol):
    BrowserSessionBoundaryError: type[Exception]

    def browser_session_model(self, *, max_tabs: int) -> _Session: ...


class _Registry(Protocol):
    def resolve(self, workspace_id: str, surface: str) -> object: ...


class _ControlModule(Protocol):
    def browser_workspace_registry(self) -> _Registry: ...


class _Policy(Protocol):
    def check_navigation(self, url: str) -> None: ...


class _PolicyModule(Protocol):
    BrowserAsideError: type[Exception]

    def BrowserEgressPolicy(self) -> _Policy: ...


class _ApiWorkspace(Protocol):
    service: object


class _ApiModule(Protocol):
    def browser_api_workspace(
        self,
        workspace_id: str,
    ) -> _ApiWorkspace: ...


def _dynamic(name: str) -> object:
    module: ModuleType = importlib.import_module(name)
    return cast(object, module)


def _session_module() -> _SessionModule:
    module: ModuleType = importlib.import_module(
        "birkin.browser_aside_session"
    )
    return cast(_SessionModule, cast(object, module))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_manager_imports_without_web_or_playwright_runtime() -> None:
    imports = _imports(_ROOT / "birkin" / "browser_aside_service.py")
    assert not any(name.startswith("birkin.web") for name in imports)
    before = set(sys.modules)
    _ = importlib.import_module("birkin.browser_aside_service")
    loaded = set(sys.modules) - before
    assert "playwright.sync_api" not in loaded


def test_transport_and_agent_resolve_same_service() -> None:
    control = cast(
        _ControlModule,
        _dynamic("birkin.browser_aside_control"),
    )
    api = cast(
        _ApiModule,
        _dynamic("birkin.web.browser_aside_workspace"),
    )
    registry = control.browser_workspace_registry()
    expected = registry.resolve("workspace-1", "agent")
    assert api.browser_api_workspace("workspace-1").service is expected
    assert registry.resolve("workspace-1", "terminal") is expected


def test_session_tab_and_action_boundaries_reject_stale_tokens() -> None:
    module = _session_module()
    session = module.browser_session_model(max_tabs=2)
    first = session.open_tab("https://example.com/")
    second = session.open_tab("https://example.org/")
    session.activate(first.tab_id)
    session.action(first.tab_id, first.generation, "click")
    with pytest.raises(module.BrowserSessionBoundaryError):
        session.action(second.tab_id, first.generation, "click")
    with pytest.raises(module.BrowserSessionBoundaryError):
        _ = session.open_tab("https://third.example/")


def test_shared_policy_gate_has_scheme_denial_parity() -> None:
    policy = cast(
        _PolicyModule,
        _dynamic("birkin.browser_aside_policy"),
    )
    with pytest.raises(PermissionError):
        BrowserPolicyGate().check_navigation("file:///etc/passwd")
    with pytest.raises(policy.BrowserAsideError) as captured:
        policy.BrowserEgressPolicy().check_navigation(
            "file:///etc/passwd"
        )
    error = cast(object, captured.value)
    assert getattr(error, "code", None) == "unsupported_scheme"


def test_core_browser_modules_never_import_web_ui() -> None:
    for name in (
        "browser_aside_control.py",
        "browser_aside_engine.py",
        "browser_aside_playwright.py",
        "browser_aside_policy.py",
        "browser_aside_service.py",
        "browser_aside_store.py",
    ):
        imports = _imports(_ROOT / "birkin" / name)
        assert not any(
            imported.startswith("birkin.web") for imported in imports
        )
