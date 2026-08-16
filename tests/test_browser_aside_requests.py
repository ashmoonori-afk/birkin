from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from birkin import store
from birkin.browser_aside_action import BrowserActionAuthority
from birkin.browser_aside_engine import BrowserRequest
from birkin.browser_aside_events import BrowserEventBridge
from birkin.browser_aside_policy import (
    BrowserEgressPolicy,
    browser_action_authority,
)
from birkin.browser_aside_requests import BrowserRequestAuthority
from birkin.sandbox import NetworkPolicy, SandboxPolicy


@dataclass
class _Request:
    url: str
    method: str = "GET"
    post_data: str | None = None
    resource_type: str = "document"
    redirected_from: BrowserRequest | None = None
    navigation: bool = True

    def is_navigation_request(self) -> bool:
        return self.navigation


@dataclass
class _Route:
    request: BrowserRequest
    continued: bool = False
    error_code: str = ""

    def continue_(self) -> None:
        self.continued = True

    def abort(self, error_code: str = "failed") -> None:
        self.error_code = error_code


def _authority(
    tmp_path: Path,
    events: list[dict[str, object]],
) -> BrowserRequestAuthority:
    policy = BrowserEgressPolicy(
        policy=SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("example.com",),
        ),
        resolver=lambda _host: ("93.184.216.34",),
    )
    actions: BrowserActionAuthority = browser_action_authority(
        egress=policy.gate,
        secrets=(),
        jail_root=str(tmp_path / "exchange"),
    )
    bridge = BrowserEventBridge(
        session_id="browser-session",
        actor_id="browser:page",
        clock=lambda: 1.0,
        append=events.append,
        browser_generation=1,
        browser_revision=1,
    )
    return BrowserRequestAuthority(
        policy=policy,
        actions=actions,
        events=bridge,
    )


def test_only_explicit_and_redirect_navigation_are_admitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    events: list[dict[str, object]] = []
    authority = _authority(tmp_path, events)
    authority.admit_navigation("https://example.com")
    explicit = _Route(_Request("https://example.com/"))
    authority.route(explicit)
    assert explicit.continued is True

    scripted = _Route(_Request("https://example.com/next"))
    authority.route(scripted)
    assert scripted.error_code == "blockedbyclient"
    assert store.list_pending() == []

    redirect = _Route(_Request(
        "https://example.com/final",
        redirected_from=_Request("https://example.com/start"),
    ))
    authority.route(redirect)
    assert redirect.continued is True


def test_form_secrets_and_websockets_fail_closed_without_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    events: list[dict[str, object]] = []
    authority = _authority(tmp_path, events)
    secret = "PRIVATE-SENTINEL-9911"
    form = _Route(_Request(
        "https://example.com/submit",
        method="POST",
        post_data=f"api_key={secret}",
    ))
    authority.route(form)
    assert form.error_code == "blockedbyclient"

    websocket = _Route(_Request(
        "https://example.com/socket",
        resource_type="websocket",
        navigation=False,
    ))
    authority.route(websocket)
    assert websocket.error_code == "blockedbyclient"
    serialized = repr((events, store.list_pending()))
    assert secret not in serialized
