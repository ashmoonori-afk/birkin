"""HTTP handlers that connect only to the address validated for a request."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from typing import TYPE_CHECKING, ClassVar


class UnsafeAddress(ValueError):
    """A hostname did not resolve exclusively to public addresses."""


def is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def resolve_public(host: str, port: int) -> str:
    try:
        addresses = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UnsafeAddress("host resolution failed") from exc
    if not addresses:
        raise UnsafeAddress("host did not resolve")

    selected: str | None = None
    for address in addresses:
        value = str(address[4][0])
        if not is_public_ip(value):
            raise UnsafeAddress("host resolves to a non-public address")
        if selected is None:
            selected = value
    if selected is None:
        raise UnsafeAddress("host did not resolve")
    return selected


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    if TYPE_CHECKING:
        source_address: ClassVar[tuple[str, int] | None]
        _tunnel_host: ClassVar[str | None]
        _context: ClassVar[ssl.SSLContext]

        def _tunnel(self) -> None: ...

    def __init__(self, host: str, *, pinned_ip: str, **kwargs) -> None:
        super().__init__(host, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )
        server_hostname = self.host
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            sock = self.sock
            server_hostname = self._tunnel_host
        self.sock = self._context.wrap_socket(
            sock,
            server_hostname=server_hostname,
        )


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    if TYPE_CHECKING:
        _context: ClassVar[ssl.SSLContext]

    def https_open(
        self,
        req: urllib.request.Request,
    ) -> http.client.HTTPResponse:
        parsed = urllib.parse.urlsplit(req.full_url)
        host = parsed.hostname or ""
        pinned_ip = resolve_public(host, parsed.port or 443)
        connection = partial(
            _PinnedHTTPSConnection,
            pinned_ip=pinned_ip,
        )
        return self.do_open(
            connection,
            req,
            context=self._context,
        )


class GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Require HTTPS and public resolution for every redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise urllib.error.HTTPError(
                newurl,
                code,
                "SSRF: HTTPS is required for redirect targets",
                headers,
                fp,
            )
        try:
            resolve_public(parsed.hostname, parsed.port or 443)
        except UnsafeAddress as exc:
            raise urllib.error.HTTPError(
                newurl,
                code,
                f"SSRF: {exc}",
                headers,
                fp,
            ) from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def pinned_opener(
    *,
    redirect_handler: urllib.request.HTTPRedirectHandler | None = None,
) -> urllib.request.OpenerDirector:
    """Build a proxy-free opener with DNS pinning and guarded redirects."""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        redirect_handler or GuardedRedirectHandler(),
        PinnedHTTPSHandler(),
    )
