from __future__ import annotations

import pytest

from birkin.browser_aside_egress import PolicyEgressGate
from birkin.browser_aside_errors import BrowserAsideError
from birkin.sandbox import NetworkPolicy, SandboxPolicy


def _policy(*hosts: str) -> SandboxPolicy:
    return SandboxPolicy(
        network=NetworkPolicy.ALLOWLIST,
        network_allowlist=hosts,
    )


def test_mixed_public_private_dns_answers_fail_closed() -> None:
    gate = PolicyEgressGate(
        _policy("mixed.example"),
        resolver=lambda _host: (
            "93.184.216.34",
            "127.0.0.1",
        ),
    )

    with pytest.raises(BrowserAsideError) as captured:
        _ = gate.evaluate("https://mixed.example/")

    assert captured.value.code == "dns_rebinding_denied"
    assert captured.value.status == 403


def test_redirect_chain_rechecks_each_destination() -> None:
    addresses = {
        "public.example": ("93.184.216.34",),
        "private.example": ("169.254.169.254",),
    }
    gate = PolicyEgressGate(
        _policy("public.example", "private.example"),
        resolver=lambda host: addresses[host],
    )

    with pytest.raises(BrowserAsideError) as captured:
        _ = gate.follow_redirects((
            "https://public.example/start",
            "https://private.example/metadata",
        ))

    assert captured.value.code == "private_network_denied"
    assert captured.value.status == 403
