"""Loopback request and privacy boundaries for Native Browser Aside."""

from __future__ import annotations

import html
import re
import secrets
import unicodedata
from collections.abc import Callable
from threading import Lock
from time import monotonic
from typing import cast, final
from urllib.parse import urlsplit, urlunsplit

_SENSITIVE_KEYS = frozenset(
    {"authorization", "cookie", "set-cookie", "password", "secret", "token"}
)
_SECRET_PATTERN = re.compile(
    r"(?i)(?:private|secret|token|bearer|session)[-_A-Za-z0-9=:.]+"
)
_FRAME_HEADERS = frozenset(
    {
        "X-Birkin-Frame-Digest",
        "X-Birkin-Frame-Ref",
        "X-Birkin-Frame-Revision",
    }
)


@final
class BrowserRequestDenied(PermissionError):
    def __init__(self, code: str, safe_message: str, status: int = 403) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status = status


@final
class BrowserRequestGuard:
    def __init__(
        self,
        *,
        port: int,
        capability: str,
        bootstrap_nonce: str,
        external_origin: str | None = None,
        clock: Callable[[], float] = monotonic,
        bootstrap_ttl_seconds: float = 60.0,
    ) -> None:
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origins = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }
        if external_origin is not None:
            parsed = urlsplit(external_origin)
            hosts.add(parsed.netloc)
            if parsed.port is None:
                default_port = 443 if parsed.scheme == "https" else 80
                hosts.add(f"{parsed.netloc}:{default_port}")
            origins.add(external_origin)
        self._hosts = frozenset(hosts)
        self._origins = frozenset(origins)
        self._capability = capability
        self._bootstrap_nonce = bootstrap_nonce
        self._clock = clock
        self._bootstrap_deadline = (
            clock() + bootstrap_ttl_seconds
        )
        self._bootstrap_consumed = False
        self._lock = Lock()

    def consume_bootstrap(
        self,
        nonce: str,
        *,
        host: str,
    ) -> str:
        with self._lock:
            if (
                self._bootstrap_consumed
                or self._clock() >= self._bootstrap_deadline
                or host.lower() not in self._hosts
                or not secrets.compare_digest(
                    nonce,
                    self._bootstrap_nonce,
                )
            ):
                raise BrowserRequestDenied(
                    "bootstrap_denied",
                    "Bootstrap request was denied.",
                )
            self._bootstrap_consumed = True
            self._bootstrap_nonce = ""
            return self._capability

    def authorize(
        self,
        *,
        method: str,
        path: str,
        host: str,
        origin: str | None,
        fetch_site: str | None,
        content_type: str | None,
        cookie_capability: str | None,
        header_capability: str | None,
    ) -> None:
        del path
        if host.lower() not in self._hosts:
            raise BrowserRequestDenied(
                "host_denied",
                "Request Host is not the configured WebUI authority.",
            )
        if method == "OPTIONS":
            raise BrowserRequestDenied(
                "cors_preflight_denied",
                "Cross-origin preflight is not supported.",
            )
        header_ok = bool(
            header_capability
            and secrets.compare_digest(
                header_capability,
                self._capability,
            )
        )
        cookie_ok = bool(
            cookie_capability
            and secrets.compare_digest(
                cookie_capability,
                self._capability,
            )
        )
        if not header_ok and not cookie_ok:
            raise BrowserRequestDenied(
                "capability_denied",
                "Browser capability is missing or invalid.",
            )
        if origin is not None and origin not in self._origins:
            raise BrowserRequestDenied(
                "origin_denied",
                "Request Origin is not the configured WebUI origin.",
            )
        if fetch_site is not None and fetch_site != "same-origin":
            raise BrowserRequestDenied(
                "csrf_denied",
                "Browser request is not same-origin.",
            )
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            if cookie_ok and (origin is None or fetch_site is None):
                raise BrowserRequestDenied(
                    "csrf_denied",
                    "Browser mutation requires same-origin metadata.",
                )
            if (
                method != "DELETE"
                and content_type != "application/json"
            ):
                raise BrowserRequestDenied(
                    "content_type_denied",
                    "Browser mutation requires application/json.",
                    415,
                )


@final
class BrowserPrivacyFilter:
    def display_url(self, raw_url: str) -> str:
        parsed = urlsplit(raw_url)
        if not parsed.hostname:
            return ""
        port = f":{parsed.port}" if parsed.port else ""
        host = (
            f"[{parsed.hostname}]"
            if ":" in parsed.hostname
            else parsed.hostname
        )
        return urlunsplit(
            (parsed.scheme, host + port, "/", "", "")
        )

    def observability(
        self,
        record: dict[str, object],
    ) -> dict[str, object]:
        return {
            key: self._safe_value(key, value)
            for key, value in record.items()
        }

    def frame_headers(
        self,
        headers: dict[str, str],
    ) -> dict[str, str]:
        return {
            key: value
            for key, value in headers.items()
            if key in _FRAME_HEADERS
        }

    def text(self, value: str, *, max_length: int) -> str:
        inert = "".join(
            character
            for character in value
            if unicodedata.category(character) not in {"Cc", "Cf"}
        )
        return html.escape(inert, quote=True)[:max_length]

    def _safe_value(self, key: str, value: object) -> object:
        normalized = key.lower()
        if normalized in _SENSITIVE_KEYS:
            return "[redacted]"
        if normalized == "url" and isinstance(value, str):
            return self.display_url(value)
        if isinstance(value, dict):
            nested = cast(dict[object, object], value)
            if not all(isinstance(inner, str) for inner in nested):
                return "[redacted]"
            return self.observability(
                cast(dict[str, object], nested)
            )
        if isinstance(value, str):
            return _SECRET_PATTERN.sub("[redacted]", self.text(
                value,
                max_length=300,
            ))
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return "[redacted]"


def browser_request_guard(
    *,
    port: int,
    capability: str,
    bootstrap_nonce: str,
    external_origin: str | None = None,
    clock: Callable[[], float] = monotonic,
    bootstrap_ttl_seconds: float = 60.0,
) -> BrowserRequestGuard:
    return BrowserRequestGuard(
        port=port,
        capability=capability,
        bootstrap_nonce=bootstrap_nonce,
        external_origin=external_origin,
        clock=clock,
        bootstrap_ttl_seconds=bootstrap_ttl_seconds,
    )


def browser_privacy_filter() -> BrowserPrivacyFilter:
    return BrowserPrivacyFilter()
