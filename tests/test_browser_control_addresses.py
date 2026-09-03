from __future__ import annotations

from pathlib import Path

import pytest

from birkin.browser import BrowserPolicyViolation, BrowserSession
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.browser_contracts import ConsoleMessage, NetworkEvent
from birkin.sandbox import NetworkPolicy, SandboxPolicy


class _ConnectingDriver:
    """Driver whose navigation runs the shared egress gate, like Playwright."""

    def __init__(self) -> None:
        self.policy: BrowserEgressPolicy | None = None

    def start(self, policy: BrowserEgressPolicy) -> None:
        self.policy = policy

    def navigate(self, url: str) -> str:
        assert self.policy is not None
        _destination, _pinned = self.policy.connect(url)
        return url

    def click(self, selector: str) -> None: ...

    def fill(self, selector: str, value: str) -> None: ...

    def press(self, selector: str, key: str) -> None: ...

    def execute(self, script: str) -> object:
        return None

    def screenshot(self, path: Path, *, full_page: bool) -> None: ...

    def evidence(self) -> tuple[list[ConsoleMessage], list[NetworkEvent]]:
        return ([], [])

    def close(self) -> None: ...


def _policy(*hosts: str) -> SandboxPolicy:
    return SandboxPolicy(
        network=NetworkPolicy.ALLOWLIST,
        network_allowlist=hosts,
    )


def test_session_denies_control_addresses_when_private_network_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "BIRKIN_BROWSER_CONTROL_ADDRESSES",
        "127.0.0.1:8787,localhost:8787",
    )
    driver = _ConnectingDriver()
    session = BrowserSession(
        driver,
        _policy("127.0.0.1"),
        tmp_path,
        allow_private_network=True,
        resolver=lambda _host: ("127.0.0.1",),
    )

    with pytest.raises(BrowserPolicyViolation) as captured:
        _ = session.navigate("http://127.0.0.1:8787/")

    assert "control addresses" in str(captured.value)


def test_explicit_control_addresses_still_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BIRKIN_BROWSER_CONTROL_ADDRESSES", raising=False)
    policy = BrowserEgressPolicy(
        policy=_policy("127.0.0.1"),
        resolver=lambda _host: ("127.0.0.1",),
        control_addresses=("127.0.0.1:8787",),
        allow_private_network=True,
    )

    with pytest.raises(BrowserPolicyViolation):
        policy("http://127.0.0.1:8787/")

    policy("http://127.0.0.1:9000/")
