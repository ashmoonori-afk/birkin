"""Canonical public origin for the WebUI listener."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_DNS_HOST = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)"
    + r"(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*"
)
_LEGACY_NUMERIC_HOST = re.compile(r"(?:0x[0-9a-f]+|[0-9.]+)", re.I)
_NUMERIC_TERMINAL = re.compile(r"(?:0x[0-9a-f]+|[0-9]+)", re.I)


@dataclass(frozen=True, slots=True)
class WebExternalOrigin:
    scheme: str
    authority: str

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.authority}"

    @property
    def secure(self) -> bool:
        return self.scheme == "https"

    @property
    def authorities(self) -> frozenset[str]:
        values = {self.authority}
        parsed = urlsplit(self.origin)
        if parsed.port is None:
            default_port = 443 if self.secure else 80
            values.add(f"{self.authority}:{default_port}")
        return frozenset(values)


def parse_web_external_url(value: object) -> WebExternalOrigin | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("web_external_url must be an absolute URL")
    if (
        not value.isascii()
        or value != value.strip()
        or any(
            ord(character) < 0x21 or ord(character) == 0x7F
            for character in value
        )
        or "\\" in value
    ):
        raise ValueError("web_external_url has an ambiguous authority")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("web_external_url has an invalid port") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "%" in parsed.netloc
    ):
        raise ValueError(
            "web_external_url must contain only an http(s) origin"
        )
    raw_host = parsed.hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(raw_host)
    except ValueError:
        if (
            parsed.netloc.startswith("[")
            or _LEGACY_NUMERIC_HOST.fullmatch(raw_host)
            or _NUMERIC_TERMINAL.fullmatch(
                raw_host.rsplit(".", 1)[-1]
            )
            or _DNS_HOST.fullmatch(raw_host) is None
            or len(raw_host) > 253
        ):
            raise ValueError("web_external_url has an invalid host")
        host = raw_host
        authority = host
    else:
        host = address.compressed
        authority = f"[{host}]" if address.version == 6 else host
    default_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != default_port:
        authority = f"{authority}:{port}"
    return WebExternalOrigin(parsed.scheme, authority)
