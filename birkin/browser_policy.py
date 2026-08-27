"""Compatibility navigation gate for the default Browser surface."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from birkin.browser_contracts import BrowserPolicyViolation
from birkin.sandbox import PolicyRequest, SandboxPolicy, SandboxViolation


@dataclass(frozen=True, slots=True)
class BrowserPolicyGate:
    """Apply workspace host policy before Browser driver navigation."""

    policy: SandboxPolicy | None = None
    allow_private_network: bool = False
    resolver: Callable[[str], tuple[str, ...]] | None = None

    def check_navigation(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise BrowserPolicyViolation(
                f"browser network URL must use http or https: {url}"
            )
        if parsed.username is not None or parsed.password is not None:
            raise BrowserPolicyViolation(
                "browser network URL must not contain credentials"
            )
        if self.policy is not None:
            try:
                _ = self.policy.require(
                    PolicyRequest(network_hosts=(parsed.hostname,))
                )
            except SandboxViolation as exc:
                raise BrowserPolicyViolation(str(exc)) from exc
        if self.allow_private_network:
            return
        try:
            addresses = (
                self.resolver(parsed.hostname)
                if self.resolver is not None
                else tuple({
                    str(result[4][0])
                    for result in socket.getaddrinfo(
                        parsed.hostname,
                        parsed.port,
                        type=socket.SOCK_STREAM,
                    )
                })
            )
        except (OSError, ValueError) as exc:
            raise BrowserPolicyViolation(
                "browser host resolution failed closed"
            ) from exc
        if not addresses:
            raise BrowserPolicyViolation(
                "browser host resolution returned no addresses"
            )
        if any(
            not ipaddress.ip_address(address).is_global
            for address in addresses
        ):
            raise BrowserPolicyViolation(
                "browser host resolves to a non-public address"
            )
