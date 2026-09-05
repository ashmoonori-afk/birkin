from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from birkin import config, store
from birkin.m365_graph import GraphUncertainError
from birkin.m365_mail import create_local_draft, execute_approved_send, list_messages
from birkin.tools import build_registry
from birkin.tools._types import ToolContext


class FakeGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.send_attempts = 0

    def request(self, method: str, path: str, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/me/messages?"):
            return {"value": [{"id": "source-1", "subject": "검토 요청"}]}
        if method == "POST" and path == "/me/messages":
            return {"id": "immutable-1"}
        if method == "POST" and path.endswith("/send"):
            self.send_attempts += 1
            raise GraphUncertainError("connection dropped")
        if method == "GET" and path.startswith("/me/messages/immutable-1"):
            return {"id": "immutable-1", "isDraft": False, "sentDateTime": "2026-09-05T00:00:00Z"}
        return {}


def test_mail_read_local_draft_and_uncertain_send_confirmation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    attachment = tmp_path / "quote.pdf"
    attachment.write_bytes(b"pdf")
    digest = hashlib.sha256(attachment.read_bytes()).hexdigest()
    graph = FakeGraph()

    inbox = list_messages(client=graph)
    assert inbox["messages"][0]["subject"] == "검토 요청"
    draft = create_local_draft({
        "action": "reply", "source_message_id": "source-1", "source_etag": "etag-1",
        "from_account": "ada@example.com", "to": ["lee@example.com"], "cc": ["kim@example.com"],
        "subject": "Re: 검토 요청", "body": "확인했습니다.",
        "attachments": [{"name": "quote.pdf", "uri": str(attachment), "content_hash": digest}],
    })
    # Exercise a new-message send because it binds all approved fields and attachments in one remote draft.
    draft = create_local_draft({**draft, "action": "new", "source_message_id": None})
    receipt = json.loads(execute_approved_send(draft, client=graph))

    assert receipt["state"] == "sent" and graph.send_attempts == 1
    assert [call[0] for call in graph.calls[-3:]] == ["POST", "POST", "GET"]
    posted = graph.calls[-3][2]
    assert posted["toRecipients"][0]["emailAddress"]["address"] == "lee@example.com"
    assert posted["attachments"][0]["name"] == "quote.pdf"


def test_send_rejects_changed_draft_and_attachment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    attachment = tmp_path / "a.txt"
    attachment.write_text("one", encoding="utf-8")
    digest = hashlib.sha256(attachment.read_bytes()).hexdigest()
    draft = create_local_draft({
        "action": "new", "from_account": "a@example.com", "to": ["b@example.com"],
        "subject": "subject", "body": "body",
        "attachments": [{"name": "a.txt", "uri": str(attachment), "content_hash": digest}],
    })
    attachment.write_text("two", encoding="utf-8")
    with pytest.raises(ValueError, match="attachment hash mismatch"):
        execute_approved_send(draft, client=FakeGraph())

    attachment.write_text("one", encoding="utf-8")
    raw = store._read_json(config.mail_drafts_path(), {})
    raw[draft["id"]]["body"] = "changed"
    store._write_json(config.mail_drafts_path(), raw)
    with pytest.raises(ValueError, match="draft content changed"):
        execute_approved_send(draft, client=FakeGraph())


def test_send_request_reviews_exact_recipients_body_and_attachment_hash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    draft = create_local_draft({
        "action": "new", "from_account": "a@example.com", "to": ["b@example.com"],
        "cc": [], "subject": "subject", "body": "exact body", "attachments": [],
    })
    captured = {}
    monkeypatch.setattr("birkin.approvals.propose", lambda **kwargs: captured.update(kwargs) or {"id": "approval-1"})
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})

    result = registry.execute("m365_mail_send_request", {"draft_id": draft["id"], "content_sha256": draft["content_sha256"]})

    assert not result.is_error and captured["category"] == "mail_send"
    reviewed = captured["payload"]
    assert reviewed["to"] == ["b@example.com"] and reviewed["body"] == "exact body"
    assert reviewed["content_sha256"] == draft["content_sha256"]
