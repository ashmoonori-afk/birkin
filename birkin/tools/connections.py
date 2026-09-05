"""Approval-gated Microsoft 365 connection tools."""

from __future__ import annotations

import json

from .. import approvals
from ..m365_connection import READ_SCOPES, status
from ._types import Tool, ToolContext, ToolInput, ToolResult


def _status(_data: ToolInput, _ctx: ToolContext) -> ToolResult:
    return ToolResult(json.dumps(status(), ensure_ascii=False))


def _request(data: ToolInput, ctx: ToolContext) -> ToolResult:
    action = str(data.get("action", ""))
    queued = approvals.propose(
        category="connection",
        title="Microsoft 365 연결 변경 확인",
        description=f"{action} 작업과 계정·읽기 범위를 확인한 뒤 연결 설정을 반영합니다.",
        payload=dict(data),
        cfg={},
        origin=ctx.record_source,
    )
    return ToolResult(json.dumps({**queued, "category": "connection"}, ensure_ascii=False))


def tools() -> list[Tool]:
    return [
        Tool("m365_connection_status", "Show Microsoft 365 account, delegated read scopes, and exact connection state.", {"type": "object", "properties": {}, "additionalProperties": False}, _status),
        Tool("m365_connection_request", "Request an approved Microsoft 365 connect, revoke, or reauthentication change.", {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["connect", "revoke", "reauthenticate"]},
                "account_id": {"type": "string", "minLength": 1},
                "account_name": {"type": "string", "minLength": 1},
                "scopes": {"type": "array", "items": {"type": "string", "enum": sorted(READ_SCOPES)}, "uniqueItems": True},
                "secret_env": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]+$"},
                "mcp_server": {"type": "string", "minLength": 1},
                "expires_at": {"type": ["string", "null"], "format": "date-time"},
            },
            "required": ["action"],
            "additionalProperties": False,
            "allOf": [{"if": {"properties": {"action": {"const": "connect"}}}, "then": {"required": ["account_id", "account_name", "scopes", "secret_env"]}}],
        }, _request),
    ]
