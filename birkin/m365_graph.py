"""Small Microsoft Graph v1.0 client with a fixed origin."""

from __future__ import annotations

import json
import os
import http.client
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from .m365_connection import record_sync_result, status
from .http_transport import open_no_redirect

ORIGIN = "https://graph.microsoft.com/v1.0"


class GraphError(RuntimeError):
    pass


class GraphUncertainError(GraphError):
    pass


class GraphClient:
    def __init__(self, token: str, *, timeout: float = 30.0, track_health: bool = False):
        if not token:
            raise GraphError("Microsoft 365 credential is unavailable")
        self._token = token
        self._timeout = timeout
        self._track_health = track_health

    def request(self, method: str, path: str, body: Mapping[str, object] | None = None, *, headers: Mapping[str, str] | None = None, response_limit: int = 2_000_000) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Graph path must be origin-relative")
        if isinstance(response_limit, bool) or not 1 <= response_limit <= 8_000_000:
            raise ValueError("Graph response_limit must be between 1 and 8000000")
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
            with open_no_redirect(request, timeout=self._timeout) as response:
                payload = response.read(response_limit + 1)
        except urllib.error.HTTPError as exc:
            if self._track_health:
                record_sync_result("authentication_required" if exc.code == 401 else f"http_{exc.code}")
            raise GraphError(f"Microsoft Graph returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if self._track_health:
                record_sync_result("temporarily_unavailable")
            raise GraphUncertainError("Microsoft Graph response was unavailable") from exc
        if len(payload) > response_limit:
            raise GraphError("Microsoft Graph response exceeded the size limit")
        result = json.loads(payload) if payload else {}
        if self._track_health:
            record_sync_result(None)
        return result

    def download(self, path: str, *, max_bytes: int) -> bytes:
        """Download Graph content without forwarding its bearer token on redirects."""
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Graph 다운로드 경로는 origin-relative 형식이어야 합니다")
        request = urllib.request.Request(ORIGIN + path, headers={"Authorization": f"Bearer {self._token}"})

        try:
            response = open_no_redirect(request, timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                if self._track_health:
                    record_sync_result("authentication_required" if exc.code == 401 else f"http_{exc.code}")
                raise GraphError(f"Microsoft Graph 다운로드가 HTTP {exc.code}로 실패했습니다") from exc
            location = exc.headers.get("Location")
            from urllib.parse import urlsplit
            parsed = urlsplit(location or "")
            if parsed.scheme != "https" or not parsed.hostname:
                if self._track_health:
                    record_sync_result("unsafe_download_location")
                raise GraphError("Microsoft Graph가 안전하지 않은 다운로드 위치를 반환했습니다") from exc
            try:
                response = open_no_redirect(
                    urllib.request.Request(
                        location, headers={"Accept": "application/octet-stream"}
                    ),
                    timeout=self._timeout,
                )
            except urllib.error.HTTPError as download_exc:
                if self._track_health:
                    record_sync_result(f"http_{download_exc.code}")
                raise GraphError(f"Microsoft 365 문서 다운로드가 HTTP {download_exc.code}로 실패했습니다") from download_exc
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as download_exc:
                if self._track_health:
                    record_sync_result("temporarily_unavailable")
                raise GraphUncertainError("Microsoft 365 문서 다운로드 응답을 받지 못했습니다") from download_exc
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            if self._track_health:
                record_sync_result("temporarily_unavailable")
            raise GraphUncertainError("Microsoft Graph 다운로드 응답을 받지 못했습니다") from exc
        try:
            payload = response.read(max_bytes + 1)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            if self._track_health:
                record_sync_result("temporarily_unavailable")
            raise GraphUncertainError("Microsoft 365 문서 내용을 읽지 못했습니다") from exc
        finally:
            response.close()
        if len(payload) > max_bytes:
            if self._track_health:
                record_sync_result("download_size_limit")
            raise GraphError("Microsoft 365 문서가 다운로드 크기 제한을 초과했습니다")
        if self._track_health:
            record_sync_result(None)
        return payload


def graph_client(*, allow_unverified: bool = False) -> GraphClient:
    connection = status()
    allowed = {"connected", "sync_failed"} | ({"verification_required"} if allow_unverified else set())
    if connection["state"] not in allowed:
        raise GraphError(f"Microsoft 365 connection is {connection['state']}")
    from . import store, config

    raw = store._read_json(config.connections_path(), {})
    record = raw.get("microsoft-365", {}) if isinstance(raw, dict) else {}
    secret_env = record.get("secret_env") if isinstance(record, dict) else None
    return GraphClient(os.environ.get(secret_env, "") if isinstance(secret_env, str) else "", track_health=True)


__all__ = ["GraphClient", "GraphError", "GraphUncertainError", "graph_client"]
