"""Microsoft 365 connection metadata with external secret references."""

from __future__ import annotations

import json
import os
import uuid
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
                "generation": uuid.uuid4().hex,
                "verified_identity": None,
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
            current.update({"revoked": False, "scopes": scopes, "expires_at": payload.get("expires_at"), "last_sync_error": None, "generation": uuid.uuid4().hex, "verified_identity": None, "updated_at": now})
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
    elif record.get("last_sync_error") == "authentication_required":
        state = "reauthentication_required"
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
    elif state == "connected" and (
        not isinstance(record.get("verified_identity"), Mapping)
        or record["verified_identity"].get("generation") != record.get("generation")
        or not isinstance(record["verified_identity"].get("tenant_id"), str)
        or not record["verified_identity"]["tenant_id"]
    ):
        state = "verification_required"
    return {
        "service": SERVICE,
        "state": state,
        "account": {"id": record.get("account_id"), "name": record.get("account_name")},
        "scopes": record.get("scopes", []),
        "credential": "external_secret_reference",
        "mcp_server": record.get("mcp_server"),
        "last_sync_error": record.get("last_sync_error"),
        "generation": record.get("generation"),
        "verified_identity": record.get("verified_identity"),
    }


def approval_identity() -> dict[str, object]:
    record = _read()
    if not record or record.get("revoked") is True:
        raise ValueError("Microsoft 365 connection is unavailable")
    verified = record.get("verified_identity")
    tenant_id = verified.get("tenant_id") if isinstance(verified, Mapping) else None
    if (
        not isinstance(tenant_id, str)
        or not tenant_id
        or verified.get("generation") != record.get("generation")
    ):
        raise ValueError("Microsoft 365 organization is not verified; reconnect and try again")
    return {
        "account_id": record.get("account_id"),
        "account_name": record.get("account_name"),
        "generation": record.get("generation"),
        "tenant_id": tenant_id,
    }


def _remote_identity(client: Any) -> dict[str, object]:
    principal = client.request("GET", "/me?$select=id,displayName,userPrincipalName,mail")
    organizations = client.request("GET", "/organization?$select=id")
    values = organizations.get("value") if isinstance(organizations, Mapping) else None
    if (
        not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], Mapping)
        or not isinstance(values[0].get("id"), str)
        or not values[0]["id"]
    ):
        raise ValueError("Microsoft 365 organization could not be verified")
    return {"principal": principal, "tenant_id": values[0]["id"]}


def verify_approval_identity(expected: object, client: Any) -> dict[str, object]:
    if not isinstance(expected, Mapping):
        raise ValueError("Microsoft 365 approval identity is missing")
    if not isinstance(expected.get("tenant_id"), str) or not expected["tenant_id"]:
        raise ValueError("Microsoft 365 approval tenant is missing; create a new review")
    current = approval_identity()
    if current != dict(expected):
        raise ValueError("Microsoft 365 connection changed; create a new review")
    remote = _remote_identity(client)
    principal = remote["principal"]
    if not isinstance(principal, Mapping):
        raise ValueError("Microsoft 365 account could not be verified")
    account_id = principal.get("id")
    names = {str(principal.get(key, "")).casefold() for key in ("userPrincipalName", "mail")}
    if account_id != expected.get("account_id") or str(expected.get("account_name", "")).casefold() not in names:
        raise ValueError("approved Microsoft 365 account does not match the executing account")
    if remote["tenant_id"] != expected.get("tenant_id"):
        raise ValueError("approved Microsoft 365 tenant does not match the executing tenant")
    verified = {"id": account_id, "name": expected.get("account_name"), "tenant_id": remote["tenant_id"], "generation": expected.get("generation")}
    with store.file_lock(config.connections_path()):
        record = _read()
        if (
            record.get("generation") != expected.get("generation")
            or record.get("revoked") is True
        ):
            raise ValueError("Microsoft 365 connection changed; create a new review")
        record["verified_identity"] = verified
        _write(record)
    return verified


def verified_approval_identity(client: Any | None = None) -> dict[str, object]:
    if client is None:
        from .m365_graph import graph_client

        client = graph_client(allow_unverified=True)
    record = _read()
    if not record or record.get("revoked") is True:
        raise ValueError("Microsoft 365 connection is unavailable")
    remote = _remote_identity(client)
    principal = remote["principal"]
    if not isinstance(principal, Mapping):
        raise ValueError("Microsoft 365 account could not be verified")
    names = {str(principal.get(key, "")).casefold() for key in ("userPrincipalName", "mail")}
    if principal.get("id") != record.get("account_id") or str(record.get("account_name", "")).casefold() not in names:
        raise ValueError("configured Microsoft 365 account does not match the authenticated account")
    verified = {"id": principal["id"], "name": record["account_name"], "tenant_id": remote["tenant_id"], "generation": record["generation"]}
    with store.file_lock(config.connections_path()):
        current = _read()
        if (
            current.get("generation") != record.get("generation")
            or current.get("revoked") is True
        ):
            raise ValueError("Microsoft 365 connection changed; create a new review")
        current["verified_identity"] = verified
        _write(current)
    return {
        "account_id": record["account_id"],
        "account_name": record["account_name"],
        "generation": record["generation"],
        "tenant_id": remote["tenant_id"],
    }


def current_verified_identity(client: Any) -> dict[str, object]:
    expected = verified_approval_identity(client)
    return {
        "id": expected["account_id"],
        "name": expected["account_name"],
        "tenant_id": expected["tenant_id"],
        "generation": expected["generation"],
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


__all__ = ["READ_SCOPES", "WRITE_SCOPES", "apply_approved", "approval_identity", "current_verified_identity", "record_sync_result", "status", "verified_approval_identity", "verify_approval_identity"]
