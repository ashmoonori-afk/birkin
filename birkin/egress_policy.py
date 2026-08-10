"""Immutable destination profiles and canonical outgoing bytes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .egress_scan import EgressScanError, canonical_json, inspect_payload


class EgressError(RuntimeError):
    """The inspected transfer was blocked or could not be proven complete."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    name: str
    host: str
    port: int
    path: str
    method: str
    content_types: frozenset[str]
    max_bytes: int
    auth_env: str = ""
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"


_CONTROL = re.compile(r"[\x00-\x20\x7f\\]")
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def _settings(cfg: dict[str, Any]) -> dict[str, Any]:
    settings = cfg.get("egress")
    if not isinstance(settings, dict) or settings.get("enabled") is not True:
        raise EgressError("blocked: inspected egress is disabled")
    return settings


def validate_header_value(value: str) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise EgressError("blocked: invalid authentication header value")
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise EgressError(
            "blocked: invalid authentication header value"
        ) from exc


def endpoint_from_config(cfg: dict[str, Any], name: str) -> Endpoint:
    settings = _settings(cfg)
    destinations = settings.get("destinations")
    if not isinstance(destinations, dict):
        raise EgressError("blocked: destination map is invalid")
    raw = destinations.get(name)
    if not isinstance(raw, dict):
        raise EgressError("blocked: unknown destination")
    if raw.get("automatic") is not True:
        raise EgressError("blocked: destination is not automatic")

    url = raw.get("url")
    if not isinstance(url, str) or _CONTROL.search(url):
        raise EgressError("blocked: invalid destination URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise EgressError("blocked: destination must be exact HTTPS")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port or 443
    except (UnicodeError, ValueError) as exc:
        raise EgressError("blocked: invalid destination authority") from exc
    if port != 443:
        raise EgressError("blocked: destination port must be 443")
    path = parsed.path or "/"
    if (not path.startswith("/")
            or not path.isascii()
            or _CONTROL.search(path)):
        raise EgressError("blocked: invalid destination path")

    method = str(raw.get("method", "POST")).upper()
    if method not in {"POST", "PUT", "PATCH"}:
        raise EgressError("blocked: unsupported destination method")
    content_types = raw.get("content_types")
    if (not isinstance(content_types, list)
            or not content_types
            or not all(isinstance(item, str) for item in content_types)):
        raise EgressError("blocked: invalid content type policy")
    global_limit = settings.get("max_bytes", 1048576)
    local_limit = raw.get("max_bytes", global_limit)
    if (not isinstance(global_limit, int) or isinstance(global_limit, bool)
            or not isinstance(local_limit, int) or isinstance(local_limit, bool)
            or global_limit <= 0 or local_limit <= 0):
        raise EgressError("blocked: invalid payload limit")

    auth_env = raw.get("auth_env", "")
    auth_header = raw.get("auth_header", "Authorization")
    auth_scheme = raw.get("auth_scheme", "Bearer")
    if not all(isinstance(item, str)
               for item in (auth_env, auth_header, auth_scheme)):
        raise EgressError("blocked: invalid auth policy")
    if (not _HEADER_NAME.fullmatch(auth_header)
            or _CONTROL.search(auth_scheme)):
        raise EgressError("blocked: invalid auth policy")
    return Endpoint(
        name=name,
        host=host,
        port=port,
        path=path,
        method=method,
        content_types=frozenset(content_types),
        max_bytes=min(global_limit, local_limit),
        auth_env=auth_env,
        auth_header=auth_header,
        auth_scheme=auth_scheme,
    )


def canonicalize(
    payload: str,
    content_type: str,
    endpoint: Endpoint,
    cfg: dict[str, Any],
) -> bytes:
    if not isinstance(payload, str):
        raise EgressError("blocked: payload must be text")
    if content_type not in endpoint.content_types:
        raise EgressError("blocked: content type is not allowed")
    parsed: Any = None
    try:
        if content_type == "application/json":
            body, parsed = canonical_json(payload)
        elif content_type == "text/plain":
            body = payload.encode("utf-8")
        else:
            raise EgressError("blocked: unsupported content type")
        if len(body) > endpoint.max_bytes:
            raise EgressError("blocked: payload exceeds byte limit")
        inspect_payload(
            body.decode("utf-8"),
            parsed,
            cfg,
            max_chars=endpoint.max_bytes,
        )
    except EgressScanError as exc:
        raise EgressError(str(exc)) from exc
    return body
