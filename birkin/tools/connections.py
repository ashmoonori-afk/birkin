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


def _mail_read(data: ToolInput, _ctx: ToolContext) -> ToolResult:
    from ..m365_mail import list_messages

    return ToolResult(json.dumps(list_messages(unread_only=bool(data.get("unread_only", True)), limit=int(data.get("limit", 20))), ensure_ascii=False))


def _mail_draft(data: ToolInput, _ctx: ToolContext) -> ToolResult:
    from ..m365_mail import create_local_draft

    return ToolResult(json.dumps(create_local_draft(data), ensure_ascii=False))


def _mail_send(data: ToolInput, ctx: ToolContext) -> ToolResult:
    from ..m365_mail import get_local_draft

    draft = get_local_draft(data.get("draft_id"), data.get("content_sha256"))
    queued = approvals.propose(
        category="mail_send",
        title=f"메일 발송 확인: {draft['subject']}",
        description=f"{draft['from_account']} 계정에서 {', '.join(draft['to'])}에게 메일을 발송합니다.",
        payload={**draft, "draft_id": draft["id"]},
        cfg={},
        origin=ctx.record_source,
    )
    return ToolResult(json.dumps({**queued, "category": "mail_send", "review": draft}, ensure_ascii=False))


def tools() -> list[Tool]:
    artifact = {
        "type": "object", "properties": {
            "name": {"type": "string", "minLength": 1},
            "uri": {"type": "string", "minLength": 1},
            "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        }, "required": ["name", "uri", "content_hash"], "additionalProperties": False,
    }
    draft_schema = {
        "type": "object", "properties": {
            "action": {"type": "string", "enum": ["new", "reply", "reply_all", "forward"]},
            "source_message_id": {"type": ["string", "null"]},
            "source_etag": {"type": ["string", "null"]},
            "from_account": {"type": "string", "minLength": 1},
            "to": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "cc": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string", "minLength": 1},
            "body": {"type": "string", "minLength": 1},
            "attachments": {"type": "array", "maxItems": 20, "items": artifact},
        }, "required": ["action", "from_account", "to", "subject", "body"], "additionalProperties": False,
    }
    return [
        Tool("m365_connection_status", "Show Microsoft 365 account, delegated read scopes, and exact connection state.", {"type": "object", "properties": {}, "additionalProperties": False}, _status),
        Tool("m365_connection_request", "Request an approved Microsoft 365 connect, revoke, or reauthentication change.", {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["connect", "revoke", "reauthenticate"]},
                "account_id": {"type": "string", "minLength": 1},
                "account_name": {"type": "string", "minLength": 1},
                "scopes": {"type": "array", "items": {"type": "string", "enum": sorted(READ_SCOPES | {"Mail.ReadWrite", "Mail.Send"})}, "uniqueItems": True},
                "secret_env": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]+$"},
                "mcp_server": {"type": "string", "minLength": 1},
                "expires_at": {"type": ["string", "null"], "format": "date-time"},
            },
            "required": ["action"],
            "additionalProperties": False,
            "allOf": [{"if": {"properties": {"action": {"const": "connect"}}}, "then": {"required": ["account_id", "account_name", "scopes", "secret_env"]}}],
        }, _request),
        Tool("m365_mail_read", "Read a bounded unread Microsoft 365 message projection for summarization.", {"type": "object", "properties": {"unread_only": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}, _mail_read),
        Tool("m365_mail_draft", "Create a local new, reply, reply-all, or forward draft with hash-bound attachments.", draft_schema, _mail_draft),
        Tool("m365_mail_send_request", "Request explicit approval to send one unchanged local mail draft.", {"type": "object", "properties": {"draft_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}, "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}, "required": ["draft_id", "content_sha256"], "additionalProperties": False}, _mail_send),
    ]
