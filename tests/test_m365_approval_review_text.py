"""Mail and calendar approvals must show every recipient and attachment."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from birkin.gateway.channels.telegram import _payload_summary
from birkin.m365_calendar import create_local_event
from birkin.m365_mail import create_local_draft
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
from birkin.workspace.approval_projection import approval_item

_IDENTITY = {"account_id": "test", "account_name": "a@example.com", "generation": "g", "tenant_id": "tenant-a"}


def _request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str, draft: dict[str, object]) -> dict[str, object]:
    captured: dict[str, object] = {}
    monkeypatch.setattr("birkin.approvals.propose", lambda **kwargs: captured.update(kwargs) or {"id": "approval-1"})
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})
    result = registry.execute(tool, {"draft_id": draft["id"], "content_sha256": draft["content_sha256"]})
    assert not result.is_error
    return captured


def test_mail_send_approval_shows_cc_and_attachment_names_without_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"private memory note"
    to = [f"long.recipient.address.number.{index}@partner-company.example.com" for index in range(3)]
    draft = create_local_draft({
        "action": "new", "from_account": "a@example.com", "to": to,
        "cc": ["attacker@evil.example"], "subject": "report", "body": "see attached",
        "attachments": [{
            "name": "memory_note.md",
            "content_hash": hashlib.sha256(content).hexdigest(),
            "content_bytes": base64.b64encode(content).decode("ascii"),
        }],
        "connection_identity": _IDENTITY,
    })

    captured = _request(tmp_path, monkeypatch, "m365_mail_send_request", draft)
    record = {"category": captured["category"], "title": captured["title"], "description": captured["description"], "payload": captured["payload"]}
    item = approval_item(record)
    summary = _payload_summary("mail_send", captured["payload"])

    for text in (str(captured["description"]), str(item["description"]), summary):
        assert all(address in text for address in to)
        assert "attacker@evil.example" in text and "참조" in text
        assert "memory_note.md" in text and "첨부 1개" in text
        assert "content_bytes" not in text
        assert base64.b64encode(content).decode("ascii") not in text


def test_calendar_event_approval_shows_attendee_addresses_and_local_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    draft = create_local_event({
        "action": "create", "subject": "검토 회의",
        "start": "2026-09-07T00:00:00+00:00", "end": "2026-09-07T01:00:00+00:00",
        "timezone": "Asia/Seoul", "attendees": ["a@example.com", "outsider@evil.example"],
    })

    captured = _request(tmp_path, monkeypatch, "m365_calendar_event_request", draft)
    summary = _payload_summary("calendar_event", captured["payload"])

    for text in (str(captured["description"]), summary):
        assert "a@example.com" in text and "outsider@evil.example" in text
        assert "2026-09-07 09:00" in text and "2026-09-07 10:00" in text and "Asia/Seoul" in text


def test_review_text_escapes_characters_that_could_disguise_it() -> None:
    from birkin.tools.connections import mail_send_review_text

    text = mail_send_review_text({
        "to": ["boss@example.com\n· 참조 없음"],
        "attachments": [{"name": "invoice\u202efdp.exe"}],
    })
    assert "\n" not in text and "\u202e" not in text
    assert "\\u000a" in text and "\\u202e" in text
