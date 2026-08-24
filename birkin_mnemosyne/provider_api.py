"""Anthropic Messages API adapter for provider completion."""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from http.client import HTTPResponse

from .json_types import JsonValue, load_json

Completer = Callable[[str], str]
ProviderConfig = Mapping[str, JsonValue]
_URL_OPEN: Callable[..., AbstractContextManager[HTTPResponse]] = (
    urllib.request.urlopen
)


def _config_string(cfg: ProviderConfig, key: str) -> str | None:
    value = cfg.get(key)
    return value if isinstance(value, str) else None


def _max_tokens(cfg: ProviderConfig) -> int:
    value = cfg.get("max_tokens", 4096)
    match value:
        case bool() | int() | float() | str():
            return int(value)
        case _:
            message = "max_tokens must be numeric"
            raise TypeError(message)


def _response_text(payload: JsonValue) -> str:
    match payload:
        case {"content": list() as blocks}:
            parts: list[str] = []
            for block in blocks:
                match block:
                    case {"type": "text", "text": str() as text}:
                        parts.append(text)
                    case _:
                        continue
            return "\n".join(parts)
        case _:
            return ""


def api_completer(
    cfg: ProviderConfig,
    model: str | None = None,
) -> Completer:
    """Return a stdlib-only Anthropic Messages API completer."""
    key = _config_string(cfg, "api_key") or os.environ.get("ANTHROPIC_API_KEY")
    endpoint = (
        _config_string(cfg, "api_endpoint")
        or "https://api.anthropic.com/v1/messages"
    )
    selected_model = model or _config_string(cfg, "model") or "claude-sonnet-5"
    max_tokens = _max_tokens(cfg)

    def complete(prompt: str) -> str:
        if not key:
            return "[provider-error] api: no ANTHROPIC_API_KEY / cfg['api_key']"
        body = json.dumps(
            {
                "model": selected_model,
                "max_tokens": max_tokens,
                "system": "You output only the requested JSON plan.",
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with _URL_OPEN(request, timeout=120) as response:
                payload = load_json(response.read().decode("utf-8"))
        except Exception as exc:
            # Provider boundary: backend failures are returned in-band by contract.
            return f"[provider-error] api: {str(exc)[:300]}"
        return _response_text(payload)

    return complete
