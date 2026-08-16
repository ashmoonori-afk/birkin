from __future__ import annotations

import pytest

from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_policy import BrowserEgressPolicy
from birkin.sandbox import NetworkPolicy, SandboxPolicy


def test_connected_peer_must_equal_dns_pinned_address() -> None:
    policy = BrowserEgressPolicy(
        policy=SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("public.example",),
        ),
        resolver=lambda _host: ("93.184.216.34",),
    )
    destination, pinned = policy.connect(
        "https://public.example/resource"
    )

    assert destination.host == "public.example"
    assert pinned == "93.184.216.34"
    policy.verify_peer(destination.display_url, pinned)

    with pytest.raises(BrowserAsideError) as captured:
        policy.verify_peer(destination.display_url, "127.0.0.1")

    assert captured.value.code == "peer_mismatch_denied"
    assert captured.value.status == 403


def test_connection_rechecks_dns_before_dial() -> None:
    answers = iter((
        ("93.184.216.34",),
        ("127.0.0.1",),
    ))
    policy = BrowserEgressPolicy(
        policy=SandboxPolicy(
            network=NetworkPolicy.ALLOWLIST,
            network_allowlist=("rebind.example",),
        ),
        resolver=lambda _host: next(answers),
    )
    with pytest.raises(BrowserAsideError) as captured:
        _ = policy.connect("https://rebind.example/")

    assert captured.value.code == "dns_rebinding_denied"
    assert captured.value.status == 403
