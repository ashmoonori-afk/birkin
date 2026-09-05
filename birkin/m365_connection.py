"""Microsoft 365 connection metadata with external secret references."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from . import config, store

SERVICE = "microsoft-365"
READ_SCOPES = frozenset({"User.Read", "Mail.Read", "Calendars.Read", "Files.Read"})
WRITE_SCOPES = frozenset({"Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite"})


def _read() -> dict[str, object]:
    raw = store._read_json(config.connections_path(), {})
    return dict(raw.get(SERVICE, {})) if isinstance(raw, dict) and isinstance(raw.get(SERVICE), dict) else {}


def _write(record: Mapping[str, object]) -> None:
    raw = store._read_json(config.connections_path(), {})
    connections = dict(raw) if isinstance(raw, dict) else {}
    connections[SERVICE] = dict(record)
    store._write_json(config.connections_path(), connections)


def _scopes(value: object, *, allow_mail_write: bool = False) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("scopes must be an array")
    scopes = sorted(set(value))
    allowed = READ_SCOPES | (WRITE_SCOPES if allow_mail_write else frozenset())
    if not scopes or any(not isinstance(scope, str) or scope not in allowed for scope in scopes):
        raise ValueError("only supported delegated scopes may be requested")
    return scopes


def apply_approved(payload: dict[str, Any], _on_event: object = None) -> str:
    action = payload.get("action")
    with store.file_lock(config.connections_path()):
        current = _read()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if action == "connect":
            account_id = payload.get("account_id")
            account_name = payload.get("account_name")
            secret_env = payload.get("secret_env")
            if not all(isinstance(item, str) and item.strip() for item in (account_id, account_name, secret_env)):
                raise ValueError("account_id, account_name, and secret_env are required")
            current = {
                "service": SERVICE,
                "account_id": account_id,
                "account_name": account_name,
                "scopes": _scopes(payload.get("scopes")),
                "secret_env": secret_env,
                "mcp_server": payload.get("mcp_server", SERVICE),
                "revoked": False,
                "expires_at": payload.get("expires_at"),
                "last_sync_error": None,
                "updated_at": now,
            }
        elif action == "revoke":
            if not current:
                raise ValueError("connection was not found")
            current.update({"revoked": True, "updated_at": now})
        elif action == "reauthenticate":
            if not current:
                raise ValueError("connection was not found")
            scopes = _scopes(payload["scopes"], allow_mail_write=True) if "scopes" in payload else current.get("scopes", [])
            current.update({"revoked": False, "scopes": scopes, "expires_at": payload.get("expires_at"), "last_sync_error": None, "updated_at": now})
        else:
            raise ValueError("unsupported connection action")
        _write(current)
    return json.dumps({"status": "applied", "connection": status()}, ensure_ascii=False, sort_keys=True)


def status(*, env: Mapping[str, str] | None = None) -> dict[str, object]:
    record = _read()
    if not record:
        return {"service": SERVICE, "state": "not_connected", "account": None, "scopes": []}
    secret_env = record.get("secret_env")
    token_present = isinstance(secret_env, str) and bool((env or os.environ).get(secret_env))
    state = "connected"
    if record.get("revoked") is True:
        state = "revoked"
    elif record.get("last_sync_error"):
        state = "sync_failed"
    elif isinstance(record.get("expires_at"), str):
        try:
            if datetime.fromisoformat(str(record["expires_at"])).astimezone(timezone.utc) <= datetime.now(timezone.utc):
                state = "token_expired"
        except ValueError:
            state = "reauthentication_required"
    if state == "connected" and not token_present:
        state = "reauthentication_required"
    return {
        "service": SERVICE,
        "state": state,
        "account": {"id": record.get("account_id"), "name": record.get("account_name")},
        "scopes": record.get("scopes", []),
        "credential": "external_secret_reference",
        "mcp_server": record.get("mcp_server"),
        "last_sync_error": record.get("last_sync_error"),
    }


def record_sync_result(error: str | None) -> None:
    """Record health without ever storing a token or response body."""
    with store.file_lock(config.connections_path()):
        current = _read()
        if not current:
            raise ValueError("connection was not found")
        current["last_sync_error"] = error.strip()[:200] if error else None
        current["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write(current)


__all__ = ["READ_SCOPES", "WRITE_SCOPES", "apply_approved", "record_sync_result", "status"]
