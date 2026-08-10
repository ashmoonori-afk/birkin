"""Fail-closed inspection for bytes submitted through Birkin egress."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import unquote

from .redact import redact_sensitive_text


class EgressScanError(ValueError):
    """Outgoing data contains credential-like material."""


_SENSITIVE_NAME = re.compile(
    r"(?i)(?:api[_-]?key|authorization|cookie|credential|password|passwd|"
    r"private[_-]?key|proxy[_-]?authorization|secret|token)"
)
_HEX = re.compile(r"(?i)^[0-9a-f]{16,}$")
_B64 = re.compile(r"^[A-Za-z0-9+/_-]{12,}={0,2}$")
_HEX_TOKEN = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{16,}(?![0-9a-f])")
_B64_TOKEN = re.compile(
    r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{12,}={0,2}"
    r"(?![A-Za-z0-9+/_=-])"
)
_MAX_VARIANTS = 128
_MAX_SCAN_CHARS = 65536
_MAX_ENCODING_DEPTH = 3


def _json_values(
    value: Any,
    *,
    key: str = "",
    depth: int = 0,
) -> Iterator[tuple[str, str]]:
    if depth > 16:
        raise EgressScanError("blocked: JSON nesting exceeds scan limit")
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _json_values(
                child,
                key=str(child_key),
                depth=depth + 1,
            )
        return
    if isinstance(value, list):
        for child in value:
            yield from _json_values(
                child,
                key=key,
                depth=depth + 1,
            )
        return
    if value is not None:
        yield key, str(value)


def _decode_once(value: str) -> set[str]:
    decoded: set[str] = set()
    candidates = [value]
    candidates.extend(
        match.group(0)
        for pattern in (_HEX_TOKEN, _B64_TOKEN)
        for match in pattern.finditer(value)
    )
    for candidate in dict.fromkeys(candidates):
        percent = unquote(candidate)
        if percent != candidate:
            decoded.add(percent)
        compact = "".join(candidate.split())
        if len(compact) % 2 == 0 and _HEX.fullmatch(compact):
            try:
                hex_text = bytes.fromhex(compact).decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                hex_text = ""
            if hex_text:
                decoded.add(hex_text)
        if _B64.fullmatch(compact):
            padded = compact + "=" * (-len(compact) % 4)
            for altchars in (None, b"-_"):
                try:
                    raw = base64.b64decode(
                        padded,
                        altchars=altchars,
                        validate=True,
                    )
                    decoded.add(raw.decode("utf-8"))
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    continue
        if len(decoded) >= _MAX_VARIANTS:
            raise EgressScanError("blocked: encoded scan expansion limit")
    return {item for item in decoded if item and item != value}


def _variants(
    values: list[str],
    max_chars: int = _MAX_SCAN_CHARS,
) -> Iterator[str]:
    seen: set[str] = set()
    frontier = [value for value in values if value]
    for _depth in range(3):
        next_frontier: list[str] = []
        for value in frontier:
            if value in seen:
                continue
            if len(value) > max_chars:
                raise EgressScanError("blocked: scan candidate exceeds limit")
            seen.add(value)
            yield value
            if len(seen) >= _MAX_VARIANTS:
                raise EgressScanError("blocked: encoded scan expansion limit")
            next_frontier.extend(_decode_once(value))
        frontier = next_frontier


def _secret_variants(
    secrets: list[str],
    max_chars: int,
) -> Iterator[str]:
    for secret in secrets:
        seen: set[str] = set()
        frontier = [secret]
        for _depth in range(_MAX_ENCODING_DEPTH + 1):
            next_frontier: list[str] = []
            for value in frontier:
                if value in seen or len(value) > max_chars:
                    continue
                seen.add(value)
                yield value
                raw = value.encode("utf-8")
                next_frontier.extend((
                    base64.b64encode(raw).decode("ascii"),
                    base64.urlsafe_b64encode(raw).decode("ascii"),
                    raw.hex(),
                ))
                if len(seen) + len(next_frontier) >= _MAX_VARIANTS:
                    raise EgressScanError(
                        "blocked: encoded secret expansion limit")
            frontier = next_frontier


def _configured_secrets(cfg: dict[str, Any]) -> list[str]:
    secrets: list[str] = []

    def visit(value: Any, key: str = "", depth: int = 0) -> None:
        if depth > 12:
            return
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key), depth + 1)
            return
        if isinstance(value, list):
            for child in value:
                visit(child, key, depth + 1)
            return
        if _SENSITIVE_NAME.search(key):
            text = str(value or "")
            if len(text) >= 8:
                secrets.append(text)

    visit(cfg)
    for name, value in os.environ.items():
        if _SENSITIVE_NAME.search(name) and len(value) >= 8:
            secrets.append(value)
    return secrets


def inspect_payload(
    text: str,
    parsed_json: Any,
    cfg: dict[str, Any],
    *,
    max_chars: int = _MAX_SCAN_CHARS,
) -> None:
    """Raise before egress when exact outgoing content looks sensitive."""
    leaves = list(_json_values(parsed_json)) if parsed_json is not None else []
    for key, value in leaves:
        if value and _SENSITIVE_NAME.search(key):
            raise EgressScanError(
                f"blocked: sensitive JSON field {key!r}")

    values = [text, *(value for _key, value in leaves)]
    if leaves:
        values.append("".join(value for _key, value in leaves))
    runtime_secrets = _configured_secrets(cfg)
    encoded_secrets = tuple(_secret_variants(runtime_secrets, max_chars))
    for variant in _variants(values, max_chars):
        if redact_sensitive_text(variant) != variant:
            raise EgressScanError("blocked: credential pattern detected")
        if any(secret in variant for secret in encoded_secrets):
            raise EgressScanError("blocked: runtime credential detected")


def canonical_json(text: str) -> tuple[bytes, Any]:
    """Parse once and return the immutable bytes that will be inspected/sent."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EgressScanError("blocked: invalid JSON payload") from exc
    body = json.dumps(
        parsed,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return body, parsed
