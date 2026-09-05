"""Approval-gated Microsoft 365 connection tools."""

from __future__ import annotations

import json

from .. import approvals
from ..m365_connection import READ_SCOPES, WRITE_SCOPES, status
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


def _calendar_read(data: ToolInput, _ctx: ToolContext) -> ToolResult:
    from ..m365_calendar import calendar_view

    return ToolResult(json.dumps(calendar_view(data["start"], data["end"]), ensure_ascii=False))


def _calendar_candidates(data: ToolInput, _ctx: ToolContext) -> ToolResult:
    from ..m365_calendar import propose_slots

    return ToolResult(json.dumps(propose_slots(**data), ensure_ascii=False))


def _calendar_draft(data: ToolInput, _ctx: ToolContext) -> ToolResult:
    from ..m365_calendar import create_local_event

    return ToolResult(json.dumps(create_local_event(data), ensure_ascii=False))


def _calendar_apply(data: ToolInput, ctx: ToolContext) -> ToolResult:
    from ..m365_calendar import get_local_event

    draft = get_local_event(data.get("draft_id"), data.get("content_sha256"))
    queued = approvals.propose(
        category="calendar_event",
        title=f"일정 {draft['action']} 확인: {draft['subject']}",
        description=f"{draft['start']}–{draft['end']} · 참석자 {len(draft['attendees'])}명",
        payload={**draft, "draft_id": draft["id"]},
        cfg={}, origin=ctx.record_source,
    )
    return ToolResult(json.dumps({**queued, "category": "calendar_event", "review": draft}, ensure_ascii=False))


def _meeting_prepare(data: ToolInput, _ctx: ToolContext) -> ToolResult:
    from urllib.parse import quote

    from ..m365_graph import graph_client
    from ..office.coordinator_data import canonical_office_home
    from ..office.search import search_sources
    from ..office.service import DocumentService

    event = graph_client().request("GET", f"/me/events/{quote(str(data['event_id']), safe='')}")
    subject = str(event.get("subject", ""))
    service = DocumentService(canonical_office_home())
    evidence = search_sources(subject, data["sources"], extract=service.extract_document, limit=data.get("limit", 10)) if subject else {"results": []}
    return ToolResult(json.dumps({"event": event, "evidence": evidence["results"], "unknown_attendee_availability": True}, ensure_ascii=False))


def _briefing_list(data: ToolInput, _ctx: ToolContext) -> ToolResult:
    from ..daily_briefing import latest

    return ToolResult(json.dumps({"briefings": latest(int(data.get("limit", 20)))}, ensure_ascii=False))


def _briefing_request(data: ToolInput, ctx: ToolContext) -> ToolResult:
    queued = approvals.propose(
        category="briefing_schedule", title="일일 브리핑 예약 변경 확인",
        description=f"일일 브리핑 {data.get('action')} 작업을 앱 내 알림 범위로 반영합니다.",
        payload=dict(data), cfg={}, origin=ctx.record_source,
    )
    return ToolResult(json.dumps({**queued, "category": "briefing_schedule"}, ensure_ascii=False))


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
                "scopes": {"type": "array", "items": {"type": "string", "enum": sorted(READ_SCOPES | WRITE_SCOPES)}, "uniqueItems": True},
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
        Tool("m365_calendar_read", "Read bounded occurrences, exceptions, and single events from the signed-in user's calendar.", {"type": "object", "properties": {"start": {"type": "string", "format": "date-time"}, "end": {"type": "string", "format": "date-time"}}, "required": ["start", "end"], "additionalProperties": False}, _calendar_read),
        Tool("m365_calendar_candidates", "Propose slots using self and explicitly supplied attendee busy intervals only.", {"type": "object", "properties": {
            "start": {"type": "string", "format": "date-time"}, "end": {"type": "string", "format": "date-time"},
            "duration_minutes": {"type": "integer", "minimum": 15, "maximum": 480}, "timezone_name": {"type": "string"},
            "busy": {"type": "array", "items": {"type": "object"}}, "attendees": {"type": "array", "items": {"type": "string"}},
            "attendee_busy_provided": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        }, "required": ["start", "end", "duration_minutes", "timezone_name", "busy", "attendees"], "additionalProperties": False}, _calendar_candidates),
        Tool("m365_calendar_draft", "Create a local event creation or update draft without sending invitations.", {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["create", "update"]}, "event_id": {"type": ["string", "null"]}, "source_etag": {"type": ["string", "null"]},
            "subject": {"type": "string", "minLength": 1}, "start": {"type": "string", "format": "date-time"}, "end": {"type": "string", "format": "date-time"},
            "timezone": {"type": "string"}, "is_all_day": {"type": "boolean"}, "attendees": {"type": "array", "items": {"type": "string"}},
            "location": {"type": "string"}, "body": {"type": "string"},
        }, "required": ["action", "subject", "start", "end", "timezone", "attendees"], "additionalProperties": False}, _calendar_draft),
        Tool("m365_calendar_event_request", "Request approval for one unchanged event after a final conflict and revision check.", {"type": "object", "properties": {"draft_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}, "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}, "required": ["draft_id", "content_sha256"], "additionalProperties": False}, _calendar_apply),
        Tool("m365_meeting_prepare", "Collect one event and source-located Office evidence for meeting preparation.", {"type": "object", "properties": {"event_id": {"type": "string"}, "sources": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "object"}}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["event_id", "sources"], "additionalProperties": False}, _meeting_prepare),
        Tool("list_daily_briefings", "List durable in-app daily briefings and their data basis times.", {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}, _briefing_list),
        Tool("daily_briefing_schedule_request", "Request an approved create, pause, resume, or skip change for an in-app briefing schedule.", {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["create", "pause", "resume", "skip"]}, "job_id": {"type": "string"},
            "name": {"type": "string"}, "schedule": {"type": "string"}, "timezone_name": {"type": "string"},
            "missed_policy": {"type": "string", "enum": ["run", "skip"]},
        }, "required": ["action"], "additionalProperties": False}, _briefing_request),
    ]
