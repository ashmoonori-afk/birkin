"""Fail-closed navigation policy for the persistent Browser Aside."""

from __future__ import annotations

import ipaddress
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

from birkin.browser_aside_egress import (
    BrowserDestination,
    PolicyEgressGate,
)
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_contracts import BrowserPolicyViolation
from birkin.sandbox import SandboxPolicy

if TYPE_CHECKING:
    from birkin.browser_aside_action import BrowserActionAuthority
MAX_URL_LENGTH = 2_048


def control_addresses_from_env() -> tuple[str, ...]:
    """Read the control-plane addresses published by the web server."""
    return tuple(
        address.strip()
        for address in os.environ.get(
            "BIRKIN_BROWSER_CONTROL_ADDRESSES",
            "",
        ).split(",")
        if address.strip()
    )


@final
class BrowserEgressPolicy:
    def __init__(
        self,
        *,
        policy: SandboxPolicy | None = None,
        private_network: Sequence[tuple[str, str, int]] = (),
        resolver: Callable[[str], tuple[str, ...]] | None = None,
        control_addresses: Sequence[str] = (),
        allow_private_network: bool = False,
    ) -> None:
        self._gate = PolicyEgressGate(
            policy or SandboxPolicy(),
            private_network=tuple(private_network),
            resolver=resolver,
            control_addresses=(
                *control_addresses,
                *control_addresses_from_env(),
            ),
            allow_private_network=allow_private_network,
        )

    def check_navigation(self, url: str) -> None:
        if len(url) > MAX_URL_LENGTH:
            raise BrowserAsideError(
                "invalid_url",
                "Navigation URL exceeds the maximum length.",
                400,
            )
        _ = self._gate.evaluate(url)

    def __call__(self, url: str) -> None:
        try:
            self.check_navigation(url)
        except BrowserAsideError as exc:
            raise BrowserPolicyViolation(exc.message) from exc

    def connect(self, url: str) -> tuple[BrowserDestination, str]:
        if len(url) > MAX_URL_LENGTH:
            raise BrowserAsideError(
                "invalid_url",
                "Navigation URL exceeds the maximum length.",
                400,
            )
        destination = self._gate.evaluate(url)
        return destination, self._gate.connect(url)

    def verify_peer(self, url: str, peer: str) -> None:
        _ = self._gate.connect(url, peer=peer)

    @property
    def gate(self) -> PolicyEgressGate:
        return self._gate


def private_network_rules(
    encoded: str,
) -> tuple[tuple[str, str, int], ...]:
    if not encoded:
        return ()
    try:
        raw = cast(object, json.loads(encoded))
    except json.JSONDecodeError as exc:
        raise BrowserAsideError(
            "invalid_private_network_policy",
            "Browser private-network policy is invalid.",
            500,
        ) from exc
    if not isinstance(raw, list):
        raise BrowserAsideError(
            "invalid_private_network_policy",
            "Browser private-network policy is invalid.",
            500,
        )
    rules: list[tuple[str, str, int]] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise BrowserAsideError(
                "invalid_private_network_policy",
                "Browser private-network policy is invalid.",
                500,
            )
        rule = cast(dict[object, object], item)
        host = rule.get("host")
        cidr = rule.get("cidr")
        port = rule.get("port")
        if (
            not isinstance(host, str)
            or not isinstance(cidr, str)
            or not isinstance(port, int)
            or not 1 <= port <= 65_535
        ):
            raise BrowserAsideError(
                "invalid_private_network_policy",
                "Browser private-network policy is invalid.",
                500,
            )
        try:
            _ = ipaddress.ip_network(cidr, strict=True)
        except ValueError as exc:
            raise BrowserAsideError(
                "invalid_private_network_policy",
                "Browser private-network policy is invalid.",
                500,
            ) from exc
        rules.append((host.lower().rstrip("."), cidr, port))
    return tuple(rules)


def browser_egress_policy(
    policy: SandboxPolicy,
    *,
    private_network: tuple[tuple[str, str, int], ...] = (),
    resolver: Callable[[str], tuple[str, ...]] | None = None,
    control_addresses: tuple[str, ...] = (),
) -> PolicyEgressGate:
    from birkin.browser_aside_egress import PolicyEgressGate

    return PolicyEgressGate(
        policy,
        private_network=private_network,
        resolver=resolver,
        control_addresses=control_addresses,
    )


def browser_action_authority(
    *,
    egress: PolicyEgressGate,
    secrets: tuple[str, ...],
    jail_root: str,
) -> BrowserActionAuthority:
    from birkin.browser_aside_action import BrowserActionAuthority

    Path(jail_root).resolve().mkdir(mode=0o700, parents=True, exist_ok=True)
    return BrowserActionAuthority(
        egress=egress,
        secrets_to_scan=secrets,
        jail_root=jail_root,
    )
