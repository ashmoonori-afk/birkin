"""Brokered HTTPS egress for exact, inspected payloads."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import socket
import ssl
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .egress_policy import (
    EgressError,
    Endpoint,
    canonicalize,
    endpoint_from_config,
    validate_header_value,
)

_RECEIPT_LOCK = threading.Lock()
_MAX_RESPONSE_BYTES = 65536


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_public(endpoint: Endpoint) -> str:
    try:
        infos = socket.getaddrinfo(
            endpoint.host,
            endpoint.port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise EgressError("failed-before-send: DNS resolution failed") from exc
    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses:
        raise EgressError("failed-before-send: no destination address")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or (
            isinstance(ip, ipaddress.IPv6Address)
            and ip.ipv4_mapped is not None
            and not ip.ipv4_mapped.is_global
        ):
            raise EgressError("blocked: destination resolved non-public")
    return addresses[0]


def _send_https(
    endpoint: Endpoint,
    address: str,
    body: bytes,
    headers: dict[str, str],
) -> tuple[int, bytes]:
    raw = socket.create_connection((address, endpoint.port), timeout=20)
    tls = ssl.create_default_context().wrap_socket(
        raw,
        server_hostname=endpoint.host,
    )
    conn = http.client.HTTPConnection(
        endpoint.host,
        endpoint.port,
        timeout=20,
    )
    conn.sock = tls
    try:
        conn.request(
            endpoint.method,
            endpoint.path,
            body=body,
            headers=headers,
        )
        response = conn.getresponse()
        reply = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(reply) > _MAX_RESPONSE_BYTES:
            raise EgressError("indeterminate: response exceeded byte limit")
        if 300 <= response.status < 400:
            raise EgressError("indeterminate: redirects are denied")
        return response.status, reply
    finally:
        conn.close()


def _receipt_path() -> Path:
    from .config import birkin_home
    return birkin_home() / "egress-receipts.jsonl"


def _write_receipt(_cfg: dict[str, Any], record: dict[str, Any]) -> None:
    path = _receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    with _RECEIPT_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def record_tool_receipt(
    cfg: dict[str, Any],
    *,
    operation: str,
    outcome: str,
    receipt_id: str | None = None,
    byte_count: int | None = None,
    http_status: int | None = None,
    provider: str | None = None,
) -> str | None:
    settings = cfg.get("egress")
    if (not isinstance(settings, dict)
            or settings.get("enabled") is not True
            or settings.get("enforced") is not True):
        return None
    current_id = receipt_id or str(uuid.uuid4())
    record: dict[str, Any] = {
        "receipt_id": current_id,
        "timestamp": _now(),
        "operation": operation,
        "outcome": outcome,
    }
    if byte_count is not None:
        record["bytes"] = byte_count
    if http_status is not None:
        record["http_status"] = http_status
    if provider is not None:
        record["provider"] = provider
    _write_receipt(cfg, record)
    return current_id


def _metadata(
    receipt_id: str,
    endpoint: Endpoint,
    digest: str,
    size: int,
    state: str,
    status: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "receipt_id": receipt_id,
        "destination": endpoint.name,
        "sha256": digest,
        "bytes": size,
        "state": state,
    }
    if status is not None:
        result["http_status"] = status
    return result


def submit_payload(
    cfg: dict[str, Any],
    destination: str,
    payload: str,
    content_type: str,
) -> dict[str, Any]:
    endpoint = endpoint_from_config(cfg, destination)
    receipt_id = uuid.uuid4().hex
    body: bytes
    try:
        body = canonicalize(payload, content_type, endpoint, cfg)
    except EgressError as exc:
        blocked_body = str(payload).encode("utf-8")
        digest = hashlib.sha256(blocked_body).hexdigest()
        record = _metadata(
            receipt_id, endpoint, digest, len(blocked_body), "blocked")
        record.update({"at": _now(), "reason": str(exc).split(":", 1)[0]})
        try:
            _write_receipt(cfg, record)
        except OSError as receipt_exc:
            raise EgressError(
                "blocked: blocked receipt unavailable") from receipt_exc
        raise

    digest = hashlib.sha256(body).hexdigest()
    intent = _metadata(
        receipt_id, endpoint, digest, len(body), "prepared")
    intent["at"] = _now()
    try:
        _write_receipt(cfg, intent)
    except OSError as exc:
        raise EgressError("blocked: intent receipt unavailable") from exc

    try:
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Host": endpoint.host,
            "User-Agent": "birkin-inspected-egress/1",
        }
        if endpoint.auth_env:
            credential = os.environ.get(endpoint.auth_env)
            if not credential:
                raise EgressError("failed-before-send: auth unavailable")
            headers[endpoint.auth_header] = (
                f"{endpoint.auth_scheme} {credential}".strip())
        for value in headers.values():
            validate_header_value(value)
        address = _resolve_public(endpoint)
    except EgressError as exc:
        outcome = _metadata(
            receipt_id, endpoint, digest, len(body), "failed-before-send")
        outcome.update({"at": _now(), "error": type(exc).__name__})
        try:
            _write_receipt(cfg, outcome)
        except OSError as receipt_exc:
            raise EgressError(
                "failed-before-send: outcome receipt unavailable"
            ) from receipt_exc
        raise EgressError("failed-before-send: transfer not attempted") from exc

    try:
        status, _reply = _send_https(
            endpoint,
            address,
            body,
            headers,
        )
        state = "succeeded" if 200 <= status < 300 else "failed"
    except (
        EgressError,
        OSError,
        ssl.SSLError,
        http.client.HTTPException,
    ) as exc:
        outcome = _metadata(
            receipt_id, endpoint, digest, len(body), "indeterminate")
        outcome.update({"at": _now(), "error": type(exc).__name__})
        try:
            _write_receipt(cfg, outcome)
        except OSError as receipt_exc:
            raise EgressError(
                "indeterminate: outcome receipt unavailable") from receipt_exc
        raise EgressError("indeterminate: transfer not retried") from exc

    outcome = _metadata(
        receipt_id, endpoint, digest, len(body), state, status)
    outcome["at"] = _now()
    try:
        _write_receipt(cfg, outcome)
    except OSError as exc:
        raise EgressError("indeterminate: outcome receipt unavailable") from exc
    return outcome
