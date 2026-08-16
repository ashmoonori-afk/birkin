"""Deterministic DNS-pinned egress policy for Browser Aside."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import final
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

from birkin.browser_aside_errors import BrowserAsideError
from birkin.sandbox import (
    PolicyRequest,
    SandboxPolicy,
    SandboxViolation,
)

PrivateRule = tuple[str, str, int]
Resolver = Callable[[str], tuple[str, ...]]
MAX_REDIRECT_HOPS = 20


@dataclass(frozen=True, slots=True)
class BrowserDestination:
    scheme: str
    host: str
    port: int
    display_url: str
    private: bool


@final
class PolicyEgressGate:
    def __init__(
        self,
        policy: SandboxPolicy,
        *,
        private_network: tuple[PrivateRule, ...] = (),
        resolver: Resolver | None = None,
        control_addresses: tuple[str, ...] = (),
    ) -> None:
        self._policy = policy
        self._private_network = private_network
        self._resolver = resolver or self._resolve
        self._control_addresses = frozenset(control_addresses)
        self._pins: dict[
            str,
            tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...],
        ] = {}

    def evaluate(self, url: str) -> BrowserDestination:
        parsed, host, port = self._target(url)
        addresses = self._addresses(host)
        private = any(self._private(address) for address in addresses)
        if f"{host}:{port}" in self._control_addresses:
            raise BrowserAsideError(
                "control_address_denied",
                "Birkin control addresses cannot be browsed.",
                403,
            )
        if private and not self._private_allowed(host, port, addresses):
            raise BrowserAsideError(
                "private_network_denied",
                "Private network navigation requires an exact trusted rule.",
                403,
            )
        path = parsed.path or "/"
        display = urlunsplit(
            (
                parsed.scheme,
                self._display_authority(host, port, parsed.scheme),
                path,
                "",
                "",
            )
        )
        return BrowserDestination(
            scheme=parsed.scheme,
            host=host,
            port=port,
            display_url=display,
            private=private,
        )

    def _target(
        self,
        url: str,
    ) -> tuple[SplitResult, str, int]:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise BrowserAsideError(
                "unsupported_scheme",
                "Only http and https navigation is allowed.",
                400,
            )
        if parsed.username is not None or parsed.password is not None:
            raise BrowserAsideError(
                "invalid_url",
                "Navigation URL is not allowed.",
                400,
            )
        host = parsed.hostname.lower().rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            _ = self._policy.require(
                PolicyRequest(network_hosts=(host,))
            )
        except SandboxViolation as exc:
            raise BrowserAsideError(
                "network_policy_denied",
                "Network destination is not allowed by workspace policy.",
                403,
            ) from exc
        return parsed, host, port

    def connect(self, url: str, peer: str = "") -> str:
        destination = self.evaluate(url)
        host = destination.host
        resolved = self._addresses(host)
        if peer:
            try:
                peer_address = ipaddress.ip_address(peer)
            except ValueError as exc:
                raise BrowserAsideError(
                    "peer_mismatch_denied",
                    "Connected peer does not match resolved destination.",
                    403,
                ) from exc
            if peer_address not in resolved:
                raise BrowserAsideError(
                    "peer_mismatch_denied",
                    "Connected peer does not match resolved destination.",
                    403,
                )
            if (
                any(self._private(address) for address in resolved)
                and not self._private_allowed(
                    host,
                    destination.port,
                    resolved,
                )
            ):
                raise BrowserAsideError(
                    "dns_rebinding_denied",
                    "DNS answer changed to a restricted destination.",
                    403,
                )
            return str(peer_address)
        return str(resolved[0])

    def follow_redirects(
        self,
        chain: Sequence[str],
    ) -> BrowserDestination:
        if not chain or len(chain) > MAX_REDIRECT_HOPS + 1:
            raise BrowserAsideError(
                "browser_redirect_policy",
                "Browser redirect chain exceeds the allowed limit.",
                400,
            )
        current = chain[0]
        destination = self.evaluate(current)
        for target in chain[1:]:
            current = urljoin(current, target)
            destination = self.evaluate(current)
        return destination

    def _addresses(
        self,
        host: str,
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        try:
            raw = self._resolver(host)
            addresses = tuple(ipaddress.ip_address(item) for item in raw)
        except (OSError, ValueError) as exc:
            raise BrowserAsideError(
                "dns_resolution_failed",
                "Navigation host could not be resolved.",
                400,
            ) from exc
        if not addresses:
            raise BrowserAsideError(
                "dns_resolution_failed",
                "Navigation host could not be resolved.",
                400,
            )
        if (
            any(self._private(address) for address in addresses)
            and any(not self._private(address) for address in addresses)
        ):
            raise BrowserAsideError(
                "dns_rebinding_denied",
                "DNS answer mixes public and restricted destinations.",
                403,
            )
        pinned = self._pins.get(host)
        if pinned is not None and pinned != addresses:
            raise BrowserAsideError(
                "dns_rebinding_denied",
                "DNS answer changed after destination validation.",
                403,
            )
        self._pins[host] = addresses
        return addresses

    def _private_allowed(
        self,
        host: str,
        port: int,
        addresses: tuple[
            ipaddress.IPv4Address | ipaddress.IPv6Address,
            ...,
        ],
    ) -> bool:
        for rule_host, cidr, rule_port in self._private_network:
            network = ipaddress.ip_network(cidr, strict=True)
            if (
                host == rule_host.lower().rstrip(".")
                and port == rule_port
                and all(
                    address.version == network.version
                    and address in network
                    for address in addresses
                )
            ):
                return True
        return False

    @staticmethod
    def _resolve(host: str) -> tuple[str, ...]:
        if host == "localhost" or host.endswith(".localhost"):
            return ("127.0.0.1",)
        if host == "metadata.google.internal":
            return ("169.254.169.254",)
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return tuple(sorted({str(answer[4][0]) for answer in answers}))

    @staticmethod
    def _private(
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> bool:
        return (
            not address.is_global
            or address.is_multicast
        )

    @staticmethod
    def _display_authority(host: str, port: int, scheme: str) -> str:
        shown_host = f"[{host}]" if ":" in host else host
        default = 443 if scheme == "https" else 80
        return shown_host if port == default else f"{shown_host}:{port}"
