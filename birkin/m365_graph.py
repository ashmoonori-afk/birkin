"""Small Microsoft Graph v1.0 client with a fixed origin."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from .m365_connection import status

ORIGIN = "https://graph.microsoft.com/v1.0"


class GraphError(RuntimeError):
    pass


class GraphUncertainError(GraphError):
    pass


class GraphClient:
    def __init__(self, token: str, *, timeout: float = 30.0):
        if not token:
            raise GraphError("Microsoft 365 credential is unavailable")
        self._token = token
        self._timeout = timeout

    def request(self, method: str, path: str, body: Mapping[str, object] | None = None, *, headers: Mapping[str, str] | None = None) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Graph path must be origin-relative")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request_headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"',
        }
        request_headers.update(headers or {})
        request = urllib.request.Request(
            ORIGIN + path,
            data=data,
            method=method,
            headers=request_headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            raise GraphError(f"Microsoft Graph returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GraphUncertainError("Microsoft Graph response was unavailable") from exc
        if len(payload) > 2_000_000:
            raise GraphError("Microsoft Graph response exceeded the size limit")
        return json.loads(payload) if payload else {}


def graph_client() -> GraphClient:
    connection = status()
    if connection["state"] != "connected":
        raise GraphError(f"Microsoft 365 connection is {connection['state']}")
    from . import store, config

    raw = store._read_json(config.connections_path(), {})
    record = raw.get("microsoft-365", {}) if isinstance(raw, dict) else {}
    secret_env = record.get("secret_env") if isinstance(record, dict) else None
    return GraphClient(os.environ.get(secret_env, "") if isinstance(secret_env, str) else "")


__all__ = ["GraphClient", "GraphError", "GraphUncertainError", "graph_client"]
