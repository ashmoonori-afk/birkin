from __future__ import annotations

import hashlib
import json
import base64
from io import BytesIO
from pathlib import Path

import pytest

from birkin import config, store
from birkin.m365_graph import GraphClient, GraphError, GraphUncertainError
from birkin.m365_mail import create_local_draft, execute_approved_send, list_messages
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
def _identity() -> dict[str, object]:
    return {"account_id": "test", "account_name": "a@example.com", "generation": "g", "tenant_id": "tenant-a"}


@pytest.fixture(autouse=True)
def _verified_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    store._write_json(config.connections_path(), {
        "microsoft-365": {
            "account_id": "test", "account_name": "a@example.com", "generation": "g",
            "secret_env": "TEST_TOKEN", "scopes": ["User.Read", "Mail.ReadWrite", "Mail.Send"],
            "revoked": False, "verified_identity": {"id": "test", "name": "a@example.com", "generation": "g", "tenant_id": "tenant-a"},
        },
    })
    monkeypatch.setenv("TEST_TOKEN", "token")


class FakeGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.send_attempts = 0
        self.remote: dict[str, object] = {}

    def request(self, method: str, path: str, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/me?"):
            return {"id": "test", "userPrincipalName": "a@example.com", "mail": "a@example.com"}
        if method == "GET" and path == "/organization?$select=id":
            return {"value": [{"id": "tenant-a"}]}
        if method == "GET" and path.startswith("/me/messages?"):
            return {"value": [{"id": "source-1", "subject": "검토 요청"}]}
        if method == "POST" and path == "/me/messages":
            self.remote = {**body, "id": "immutable-1", "isDraft": True, "bccRecipients": []}
            return {"id": "immutable-1"}
        if method == "POST" and path.endswith("/send"):
            self.send_attempts += 1
            raise GraphUncertainError("connection dropped")
        if method == "GET" and path.startswith("/me/messages/immutable-1"):
            return {**self.remote, "isDraft": self.send_attempts == 0, "sentDateTime": "2026-09-05T00:00:00Z" if self.send_attempts else None}
        return {}


class ActionGraph:
    def __init__(self, *, corrupt: bool = False, uncertain_once: bool = False) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.remote: dict[str, object] = {}
        self.inherited: list[dict[str, object]] = []
        self.send_count = 0
        self.corrupt = corrupt
        self.uncertain_once = uncertain_once

    def request(self, method: str, path: str, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/me?"):
            return {"id": "test", "userPrincipalName": "a@example.com", "mail": "a@example.com"}
        if method == "GET" and path == "/organization?$select=id":
            return {"value": [{"id": "tenant-a"}]}
        if method == "GET" and path.startswith("/me/messages/source-1?"):
            return {"id": "source-1", "@odata.etag": "source-v1"}
        if method == "POST" and path == "/me/messages":
            self.remote = {**body, "id": "draft-1", "isDraft": True}
            return {"id": "draft-1"}
        if method == "POST" and path.endswith(("createReply", "createReplyAll", "createForward")):
            self.remote = {"id": "draft-1", "isDraft": True}
            self.inherited = [{"id": "inherited-1", "@odata.type": "#microsoft.graph.referenceAttachment"}]
            return {"id": "draft-1"}
        if method == "GET" and "$select=id&$expand=attachments" in path:
            return {"id": "draft-1", "attachments": list(self.inherited)}
        if method == "DELETE" and "/attachments/" in path:
            self.inherited = []
            return {}
        if method == "PATCH":
            self.remote.update(body)
            return {}
        if method == "POST" and path.endswith("/send"):
            self.send_count += 1
            if self.uncertain_once and self.send_count == 1:
                self.remote["isDraft"] = False
                raise GraphUncertainError("connection dropped")
            self.remote["isDraft"] = False
            return {}
        if method == "GET" and path.startswith("/me/messages/draft-1"):
            body = dict(self.remote)
            body["attachments"] = list(self.inherited) if self.inherited else body.get("attachments", [])
            if self.corrupt:
                body["body"] = {"contentType": "Text", "content": "changed"}
            return body
        return {}


def _draft(action: str) -> dict[str, object]:
    return create_local_draft({
        "action": action,
        "source_message_id": None if action == "new" else "source-1",
        "source_etag": None if action == "new" else "source-v1",
        "from_account": "a@example.com", "to": ["b@example.com"], "cc": [],
        "subject": "subject", "body": "approved body", "attachments": [],
        "connection_identity": _identity(),
    })


@pytest.mark.parametrize("action,suffix", [
    ("new", "/me/messages"),
    ("reply", "/createReply"),
    ("reply_all", "/createReplyAll"),
    ("forward", "/createForward"),
])
def test_each_mail_action_verifies_remote_snapshot_before_one_send(
    action: str, suffix: str,
) -> None:
    graph = ActionGraph()
    draft = _draft(action)

    receipt = json.loads(execute_approved_send(draft, client=graph))
    again = json.loads(execute_approved_send(draft, client=graph))

    assert receipt["state"] == again["state"] == "observed_non_draft"
    assert graph.send_count == 1
    assert any(method == "POST" and path.endswith(suffix) for method, path, _ in graph.calls)
    if action != "new":
        assert any(method == "DELETE" and "/attachments/inherited-1" in path for method, path, _ in graph.calls)


def test_reply_remote_content_mismatch_never_sends() -> None:
    graph = ActionGraph(corrupt=True)
    with pytest.raises(ValueError, match="remote mail draft changed"):
        execute_approved_send(_draft("reply"), client=graph)
    assert graph.send_count == 0


def test_reply_uncertain_send_is_confirmed_without_duplicate() -> None:
    graph = ActionGraph(uncertain_once=True)
    draft = _draft("reply")
    first = json.loads(execute_approved_send(draft, client=graph))
    second = json.loads(execute_approved_send(draft, client=graph))
    assert first["state"] == second["state"] == "observed_non_draft"
    assert graph.send_count == 1


def test_reply_rejects_changed_source_etag_before_creating_remote_draft() -> None:
    graph = ActionGraph()
    draft = _draft("reply")
    graph.request = lambda method, path, body=None: (
        {"id": "test", "userPrincipalName": "a@example.com", "mail": "a@example.com"}
        if path.startswith("/me?") else
        {"value": [{"id": "tenant-a"}]}
        if path == "/organization?$select=id" else
        {"id": "source-1", "@odata.etag": "new-source-version"}
    )
    with pytest.raises(ValueError, match="원본 메일이 변경"):
        execute_approved_send(draft, client=graph)


def test_three_mib_attachment_uses_larger_bounded_remote_verification() -> None:
    payload = b"x" * (3 * 1024 * 1024)
    encoded = base64.b64encode(payload).decode("ascii")
    inner = ActionGraph()

    class BoundedGraph(GraphClient):
        def __init__(self) -> None:
            self.limits: list[int] = []

        def request(self, method: str, path: str, body=None, *, headers=None, response_limit: int = 2_000_000):
            self.limits.append(response_limit)
            if method == "POST" and path.endswith("/attachments"):
                inner.remote.setdefault("attachments", []).append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": body["name"],
                    "contentBytes": body["contentBytes"],
                })
                return {}
            return inner.request(method, path, body)

    graph = BoundedGraph()
    draft = create_local_draft({
        "action": "new", "from_account": "a@example.com", "to": ["b@example.com"],
        "subject": "subject", "body": "body",
        "attachments": [{"name": "full.bin", "content_bytes": encoded, "content_hash": hashlib.sha256(payload).hexdigest()}],
        "connection_identity": _identity(),
    })

    receipt = json.loads(execute_approved_send(draft, client=graph))
    assert receipt["state"] == "observed_non_draft"
    assert 5 * 1024 * 1024 in graph.limits


def test_graph_json_response_limit_is_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"value": "x" * 2_100_000}).encode()

    class Response(BytesIO):
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    monkeypatch.setattr(
        "birkin.m365_graph.open_no_redirect",
        lambda request, *, timeout: Response(payload),
    )
    with pytest.raises(GraphError, match="size limit"):
        GraphClient("secret").request("GET", "/me/messages/draft")
    result = GraphClient("secret").request(
        "GET", "/me/messages/draft", response_limit=5 * 1024 * 1024,
    )
    assert len(result["value"]) == 2_100_000


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
        "from_account": "a@example.com", "to": ["lee@example.com"], "cc": ["kim@example.com"],
        "subject": "Re: 검토 요청", "body": "확인했습니다.",
        "attachments": [{"name": "quote.pdf", "uri": str(attachment), "content_hash": digest}],
        "connection_identity": _identity(),
    })
    # Exercise a new-message send because it binds all approved fields and attachments in one remote draft.
    draft = create_local_draft({**draft, "action": "new", "source_message_id": None})
    receipt = json.loads(execute_approved_send(draft, client=graph))

    assert receipt["state"] == "submitted" and graph.send_attempts == 1
    posted = next(body for method, path, body in graph.calls if method == "POST" and path == "/me/messages")
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
        "connection_identity": _identity(),
    })
    attachment.write_text("two", encoding="utf-8")
    graph = FakeGraph()
    _ = execute_approved_send(draft, client=graph)
    posted = next(body for method, path, body in graph.calls if method == "POST" and path == "/me/messages")
    assert posted["attachments"][0]["contentBytes"] == "b25l"

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
        "connection_identity": _identity(),
    })
    captured = {}
    monkeypatch.setattr("birkin.approvals.propose", lambda **kwargs: captured.update(kwargs) or {"id": "approval-1"})
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})

    result = registry.execute("m365_mail_send_request", {"draft_id": draft["id"], "content_sha256": draft["content_sha256"]})

    assert not result.is_error and captured["category"] == "mail_send"
    reviewed = captured["payload"]
    assert reviewed["to"] == ["b@example.com"] and reviewed["body"] == "exact body"
    assert reviewed["content_sha256"] == draft["content_sha256"]


def test_mail_recheck_tool_accepts_only_the_existing_approval_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "birkin.approval_execution_recovery.recheck_unknown_mail_send",
        lambda approval_id: {"ok": True, "state": "accepted", "approval_id": approval_id},
    )
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})
    spec = next(item for item in registry.specs() if item["name"] == "m365_mail_send_recheck")

    result = registry.execute("m365_mail_send_recheck", {"approval_id": "a" * 12})

    assert not result.is_error
    assert json.loads(str(result.content))["approval_id"] == "a" * 12
    assert spec["input_schema"] == {
        "type": "object",
        "properties": {"approval_id": {"type": "string", "pattern": "^[0-9a-f]{12}$"}},
        "required": ["approval_id"],
        "additionalProperties": False,
    }


def test_send_rejects_approved_sender_different_from_connection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    draft = create_local_draft({
        "action": "new", "from_account": "b@example.com", "to": ["b@example.com"],
        "subject": "subject", "body": "body", "attachments": [],
        "connection_identity": _identity(),
    })
    with pytest.raises(ValueError, match="approved sender"):
        execute_approved_send(draft, client=FakeGraph())
