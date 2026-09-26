from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from birkin import (
    approval_dispatch,
    approval_execution,
    approval_execution_helper,
    approval_execution_recovery,
    config,
    store,
)
from birkin.approval_execution_journal import ExecutionJournal, authority_digest
from birkin.approval_execution_state import JournalPhase
from birkin.m365_graph import GraphError
from birkin.m365_mail import (
    _observed_state,
    _remote_matches,
    create_local_draft,
    execute_approved_send,
    reconcile_approved_send,
)
from birkin.workspace.approval_projection import approval_item


@pytest.fixture(autouse=True)
def _account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    store._write_json(config.connections_path(), {"microsoft-365": {
        "account_id": "test", "account_name": "a@example.com", "generation": "g",
        "secret_env": "TEST_TOKEN", "scopes": ["Mail.ReadWrite", "Mail.Send"],
        "revoked": False, "verified_identity": {
            "id": "test", "name": "a@example.com", "generation": "g", "tenant_id": "tenant-a",
        },
    }})


_MISSING = object()


class Graph202:
    def __init__(self, observation: object, *, sent_at: str = "2026-09-06T00:00:00Z", corrupt_sent: bool = False) -> None:
        self.observation = observation
        self.sent_at = sent_at
        self.corrupt_sent = corrupt_sent
        self.creates = 0
        self.sends = 0
        self.message_gets = 0
        self.remote: dict[str, object] = {}

    def request(self, method: str, path: str, body=None):
        if method == "GET" and path.startswith("/me?"):
            return {"id": "test", "userPrincipalName": "a@example.com", "mail": "a@example.com"}
        if method == "GET" and path == "/organization?$select=id":
            return {"value": [{"id": "tenant-a"}]}
        if method == "POST" and path == "/me/messages":
            self.creates += 1
            self.remote = {**body, "id": "draft-1", "isDraft": True}
            return {"id": "draft-1"}
        if method == "POST" and path.endswith("/send"):
            self.sends += 1
            return {}
        if method == "GET" and path.startswith("/me/messages/draft-1"):
            self.message_gets += 1
            if "sentDateTime" in path:
                if isinstance(self.observation, Exception):
                    raise self.observation
                result = {
                    **self.remote,
                    "isDraft": self.observation,
                    "sentDateTime": self.sent_at if self.observation is False else None,
                }
                if self.observation is _MISSING:
                    result.pop("isDraft")
                if self.corrupt_sent:
                    result["subject"] = "different"
                return result
            return self.remote
        raise AssertionError((method, path))


def _draft() -> dict[str, object]:
    return create_local_draft({
        "action": "new", "from_account": "a@example.com", "to": ["b@example.com"],
        "subject": "subject", "body": "body", "attachments": [],
        "connection_identity": {
            "account_id": "test", "account_name": "a@example.com", "generation": "g", "tenant_id": "tenant-a",
        },
    })


def _unknown_approval(draft: dict[str, object]) -> str:
    proposal = store.add_pending(
        category="mail_send", title="Send", description="",
        payload={"draft_id": draft["id"], "content_sha256": draft["content_sha256"]},
        origin="test",
    )
    approval_id = str(proposal["id"])
    journal = ExecutionJournal(approval_id)
    journal.arm(authority_digest(proposal), "mail_send", proposal["payload"])
    journal.ready()
    journal.helper_started(owner_pid=1)
    journal.commit_attempt(owner_pid=1)
    journal.outcome_unknown()
    _ = store.resolve_pending(approval_id, "action_outcome_unknown")
    return approval_id


@pytest.mark.parametrize(("observation", "state"), [
    (True, "accepted"),
    (False, "submitted"),
    (GraphError("not observable"), "accepted"),
])
def test_graph_202_is_accepted_until_remote_submission_is_observed(
    observation: bool | Exception, state: str,
) -> None:
    graph = Graph202(observation)
    draft = _draft()

    first = json.loads(execute_approved_send(draft, client=graph))
    second = json.loads(execute_approved_send(draft, client=graph))

    assert first["state"] == state
    assert second["state"] in {state, "unknown"}
    assert graph.sends == 1


def test_reconciliation_rejects_changed_approval_account() -> None:
    graph = Graph202(True)
    draft = _draft()
    _ = execute_approved_send(draft, client=graph)
    raw = store._read_json(config.mail_drafts_path(), {})
    raw[draft["id"]]["connection_identity"]["tenant_id"] = "tenant-b"
    store._write_json(config.mail_drafts_path(), raw)

    with pytest.raises(ValueError, match="content changed"):
        reconcile_approved_send(draft, client=graph)


def test_invalid_sent_timestamp_does_not_claim_submission() -> None:
    graph = Graph202(False, sent_at="not-a-date")

    receipt = json.loads(execute_approved_send(_draft(), client=graph))

    assert receipt["state"] == "observed_non_draft"


@pytest.mark.parametrize("sent_at", ["2026-09-06T00:00:00", "0001-01-01T00:00:00Z"])
def test_sent_timestamp_must_be_real_and_offset_aware(sent_at: str) -> None:
    assert _observed_state({"isDraft": False, "sentDateTime": sent_at}) == (
        "observed_non_draft"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attachments", None),
        ("attachments", {}),
        ("ccRecipients", None),
        ("ccRecipients", [{}]),
        ("bccRecipients", None),
        ("bccRecipients", [{}]),
    ],
)
def test_remote_match_requires_explicit_well_formed_empty_collections(
    field: str, value: object,
) -> None:
    draft = {
        "subject": "subject", "body": "body", "to": ["b@example.com"],
        "cc": [], "attachments": [],
    }
    remote = {
        "subject": "subject",
        "body": {"contentType": "Text", "content": "body"},
        "toRecipients": [{"emailAddress": {"address": "b@example.com"}}],
        "ccRecipients": [], "bccRecipients": [], "attachments": [],
    }
    if value is None:
        remote.pop(field)
    else:
        remote[field] = value

    assert _remote_matches(draft, remote) is False


def test_remote_match_rejects_partial_attachment_page() -> None:
    draft = {
        "subject": "subject", "body": "body", "to": ["b@example.com"],
        "cc": [], "attachments": [],
    }
    remote = {
        "subject": "subject",
        "body": {"contentType": "Text", "content": "body"},
        "toRecipients": [{"emailAddress": {"address": "b@example.com"}}],
        "ccRecipients": [], "bccRecipients": [], "attachments": [],
        "attachments@odata.nextLink": "https://graph.example/next",
    }

    assert _remote_matches(draft, remote) is False


@pytest.mark.parametrize("content_type", [None, "HTML"])
def test_remote_match_rejects_missing_or_changed_body_type(
    content_type: str | None,
) -> None:
    draft = {
        "subject": "subject", "body": "<b>name</b>",
        "to": ["b@example.com"], "cc": [], "attachments": [],
    }
    body = {"content": "<b>name</b>"}
    if content_type is not None:
        body["contentType"] = content_type
    remote = {
        "subject": "subject", "body": body,
        "toRecipients": [{"emailAddress": {"address": "b@example.com"}}],
        "ccRecipients": [], "bccRecipients": [], "attachments": [],
    }

    assert _remote_matches(draft, remote) is False


def test_reentry_get_failure_preserves_durable_acceptance() -> None:
    graph = Graph202(GraphError("not observable"))
    draft = _draft()

    first = json.loads(execute_approved_send(draft, client=graph))
    second = json.loads(execute_approved_send(draft, client=graph))
    reconciled = json.loads(reconcile_approved_send(draft, client=graph))

    assert first["state"] == second["state"] == reconciled["state"] == "accepted"
    assert graph.sends == 1


@pytest.mark.parametrize("observation", [_MISSING, None, "false"])
def test_remote_draft_reentry_requires_exact_draft_observation(observation: object) -> None:
    graph = Graph202(observation)
    draft = _draft()
    graph.remote = {
        "id": "draft-1", "subject": "subject",
        "body": {"contentType": "Text", "content": "body"},
        "toRecipients": [{"emailAddress": {"address": "b@example.com"}}],
        "ccRecipients": [], "bccRecipients": [], "attachments": [],
    }
    store._write_json(config.mail_receipts_path(), {
        draft["content_sha256"]: {"remote_id": "draft-1", "state": "remote_draft_created"},
    })

    receipt = json.loads(execute_approved_send(draft, client=graph))

    assert receipt["state"] == "needs_review"
    assert graph.creates == graph.sends == 0


def test_manual_recheck_uses_get_only_and_confirms_graph_processing() -> None:
    draft = _draft()
    approval_id = _unknown_approval(draft)
    store._write_json(config.mail_receipts_path(), {
        draft["content_sha256"]: {
            "draft_id": draft["id"], "content_sha256": draft["content_sha256"],
            "remote_id": "draft-1", "state": "accepted",
        },
    })
    graph = Graph202(False)
    graph.remote = {
        "id": "draft-1", "subject": "subject",
        "body": {"contentType": "Text", "content": "body"},
        "toRecipients": [{"emailAddress": {"address": "b@example.com"}}],
        "ccRecipients": [], "bccRecipients": [], "attachments": [],
    }

    result = approval_execution_recovery.recheck_unknown_mail_send(
        approval_id, client=graph,
    )

    assert result["state"] == "submitted"
    assert result["message"] == "Microsoft 365 발송 처리가 확인되었습니다"
    assert graph.creates == graph.sends == 0


def test_manual_recheck_revoked_connection_makes_no_graph_request() -> None:
    draft = _draft()
    approval_id = _unknown_approval(draft)
    store._write_json(config.mail_receipts_path(), {
        draft["content_sha256"]: {
            "draft_id": draft["id"], "content_sha256": draft["content_sha256"],
            "remote_id": "draft-1", "state": "accepted",
        },
    })
    connection = store._read_json(config.connections_path(), {})
    connection["microsoft-365"]["revoked"] = True
    store._write_json(config.connections_path(), connection)

    class NoGraphCalls:
        def request(self, method: str, path: str, body=None):
            raise AssertionError((method, path, body))

    result = approval_execution_recovery.recheck_unknown_mail_send(
        approval_id, client=NoGraphCalls(),
    )

    assert result["state"] == "needs_review"
    assert result["recheckable"] is False
    assert result["message"] == "연결 계정 또는 승인 내용을 확인할 수 없어 검토가 필요합니다"


def test_manual_needs_review_is_terminal_even_if_remote_later_matches() -> None:
    draft = _draft()
    approval_id = _unknown_approval(draft)
    store._write_json(config.mail_receipts_path(), {
        draft["content_sha256"]: {
            "draft_id": draft["id"], "content_sha256": draft["content_sha256"],
            "remote_id": "draft-1", "state": "accepted",
        },
    })
    graph = Graph202(False, corrupt_sent=True)
    graph.remote = {
        "id": "draft-1", "subject": "subject",
        "body": {"contentType": "Text", "content": "body"},
        "toRecipients": [{"emailAddress": {"address": "b@example.com"}}],
        "ccRecipients": [], "bccRecipients": [], "attachments": [],
    }

    first = approval_execution_recovery.recheck_unknown_mail_send(
        approval_id, client=graph,
    )
    first_record = store.get_pending(approval_id)
    graph.corrupt_sent = False
    second = approval_execution_recovery.recheck_unknown_mail_send(
        approval_id, client=graph,
    )
    second_record = store.get_pending(approval_id)

    assert first["state"] == second["state"] == "needs_review"
    assert first["mail_rechecked_at"] == second["mail_rechecked_at"]
    assert graph.message_gets == 1
    assert graph.creates == graph.sends == 0
    assert first_record == second_record
    assert ExecutionJournal(approval_id).load().phase.value == "action_outcome_unknown"


def _queued_send(draft: dict[str, object]) -> str:
    proposal = store.add_pending(
        category="mail_send", title="Send", description="",
        payload={"draft_id": draft["id"], "content_sha256": draft["content_sha256"]},
        origin="test",
    )
    return str(proposal["id"])


def _dispatch(category: str, payload: dict[str, object], *args: object, **kwargs: object) -> str:
    del args, kwargs
    return approval_dispatch.execute_action(category, payload)


def _approve(approval_id: str) -> dict[str, object]:
    return approval_execution.approve(
        approval_id, _dispatch, approved_by="human:test", approved_via="test",
    )


@pytest.mark.parametrize("observation", [True, GraphError("not observable")])
def test_approved_send_that_graph_only_accepted_is_an_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch, observation: bool | Exception,
) -> None:
    graph = Graph202(observation)
    monkeypatch.setattr("birkin.m365_mail.graph_client", lambda: graph)
    approval_id = _queued_send(_draft())

    result = _approve(approval_id)

    assert result["ok"] is False
    assert result["state"] == "accepted" and result["recheckable"] is True
    assert str(result["error"]).startswith("Microsoft 365가 요청을 접수했지만")
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "action_outcome_unknown"
    item = approval_item(record)
    assert item["ui_state"] == "action_needed" and item["recheckable"] is True
    assert item["mail_recheck_state"] == "accepted"
    assert ExecutionJournal(approval_id).load().phase is JournalPhase.ACTION_OUTCOME_UNKNOWN

    graph.observation = False
    rechecked = approval_execution_recovery.recheck_unknown_mail_send(
        approval_id, client=graph,
    )

    assert rechecked["state"] == "submitted"
    confirmed = store.get_pending(approval_id)
    assert confirmed is not None and confirmed["status"] == "approved"
    assert graph.sends == 1


def test_workspace_approval_of_an_accepted_send_is_unconfirmed_not_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from birkin import approvals
    from birkin.workspace import WorkspaceEvent
    from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter

    graph = Graph202(True)
    monkeypatch.setattr("birkin.m365_mail.graph_client", lambda: graph)
    monkeypatch.setattr(approvals, "execute_action", _dispatch)
    approval_id = _queued_send(_draft())
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return WorkspaceEvent(
            protocol_version=1, session_id="mail-session", cursor=len(emitted),
            event_id=f"event-{len(emitted)}", type=event_type,
            timestamp="2026-09-26T00:00:00Z", actor_id="web:test",
            command_id="command-1", payload=payload,
        )

    adapter = RuntimeWorkspaceAdapter(
        "mail-session", emit, workspace_root=tmp_path / "workspace",
    )
    result = adapter.handlers()["approval.answer"](
        {"approval_id": approval_id, "decision": "approve"}
    )

    assert result["state"] == "accepted" and result["recheckable"] is True
    answered = next(payload for kind, payload in emitted if kind == "approval.answered")
    assert answered["result_code"] == "E_APPROVAL_OUTCOME_UNKNOWN"
    assert str(answered["result_summary"]).startswith("Microsoft 365가 요청을 접수했지만")
    assert answered["ui_state"] == "action_needed"
    context = str(getattr(adapter, "_pending_approval_context"))
    assert "완료하지 못했습니다" not in context
    assert "발송 처리는 아직 확인되지 않았습니다" in context
    assert graph.sends == 1


def test_approved_send_observed_as_submitted_is_still_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Graph202(False)
    monkeypatch.setattr("birkin.m365_mail.graph_client", lambda: graph)
    approval_id = _queued_send(_draft())

    result = _approve(approval_id)

    assert result["ok"] is True
    assert json.loads(str(result["result"]))["state"] == "submitted"
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "approved"
    assert ExecutionJournal(approval_id).load().phase is JournalPhase.SUCCEEDED


def test_sent_mail_that_differs_from_approval_is_never_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Graph202(False, corrupt_sent=True)
    monkeypatch.setattr("birkin.m365_mail.graph_client", lambda: graph)
    approval_id = _queued_send(_draft())

    result = _approve(approval_id)

    assert result["ok"] is False
    assert result["state"] == "needs_review" and result["recheckable"] is False
    assert "Outlook 보낸 편지함" in str(result["error"])
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "action_outcome_unknown"
    assert approval_item(record)["recheckable"] is False
    gets = graph.message_gets

    rechecked = approval_execution_recovery.recheck_unknown_mail_send(
        approval_id, client=graph,
    )

    assert rechecked["state"] == "needs_review"
    assert graph.message_gets == gets


def test_helper_process_records_an_accepted_send_as_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Graph202(True)
    monkeypatch.setattr("birkin.m365_mail.graph_client", lambda: graph)
    approval_id = _queued_send(_draft())
    assert approval_execution.claim(
        approval_id, approved_by="human:test", approved_via="test",
    ) == {"ok": True}
    record = store.get_pending(approval_id)
    assert record is not None
    journal = ExecutionJournal(approval_id)
    journal.arm(authority_digest(record), "mail_send", record["payload"])
    journal.ready()
    _ = store.resolve_pending(approval_id, "executing")

    assert approval_execution_helper.run(approval_id, "local") == 0

    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "action_outcome_unknown"
    assert record["mail_recheck_state"] == "accepted"
    assert record["recheckable"] is True
    projected = approval_execution_recovery.recover_one(approval_id)
    assert projected is not None
    assert projected["ok"] is False and projected["state"] == "accepted"
    assert graph.sends == 1


def test_crashed_committed_send_recovers_accepted_receipt_as_recheckable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Graph202(True)
    monkeypatch.setattr("birkin.m365_mail.graph_client", lambda: graph)
    draft = _draft()
    assert json.loads(execute_approved_send(draft, client=graph))["state"] == "accepted"
    approval_id = _queued_send(draft)
    record = store.get_pending(approval_id)
    assert record is not None
    journal = ExecutionJournal(approval_id)
    journal.arm(authority_digest(record), "mail_send", record["payload"])
    journal.ready()
    journal.helper_started(owner_pid=999_999, owner_token="dead")
    journal.commit_attempt(owner_pid=999_999, owner_token="dead")
    _ = store.resolve_pending(approval_id, "executing")

    recovered = approval_execution_recovery.recover_one(approval_id)

    assert recovered is not None
    assert recovered["ok"] is False
    assert recovered["state"] == "accepted" and recovered["recheckable"] is True
    assert journal.load().phase is JournalPhase.ACTION_OUTCOME_UNKNOWN
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "action_outcome_unknown"
    assert record["mail_recheck_state"] == "accepted"
    assert record["recheckable"] is True
    assert graph.sends == 1


def test_reprojection_keeps_a_later_manual_recheck_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Graph202(True)
    monkeypatch.setattr("birkin.m365_mail.graph_client", lambda: graph)
    approval_id = _queued_send(_draft())
    assert _approve(approval_id)["state"] == "accepted"
    graph.observation = False
    graph.corrupt_sent = True
    rechecked = approval_execution_recovery.recheck_unknown_mail_send(
        approval_id, client=graph,
    )
    assert rechecked["state"] == "needs_review"

    # Startup recovery re-projects every terminal journal, whose result is
    # still the original "accepted" receipt.
    projected = approval_execution_recovery.recover_one(approval_id)

    assert projected is not None and projected["state"] == "needs_review"
    record = store.get_pending(approval_id)
    assert record is not None
    assert record["mail_recheck_state"] == "needs_review"
    assert record["recheckable"] is False


def test_unconfirmed_send_is_not_reported_failed_when_projection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = Graph202(True)
    monkeypatch.setattr("birkin.m365_mail.graph_client", lambda: graph)
    approval_id = _queued_send(_draft())
    real_resolve = store.resolve_pending

    def failing_resolve(aid: str, status: str, *args: object, **kwargs: object) -> object:
        if status == "action_outcome_unknown":
            raise PermissionError("forced state file contention")
        return real_resolve(aid, status, *args, **kwargs)

    monkeypatch.setattr(store, "resolve_pending", failing_resolve)
    result = _approve(approval_id)

    assert result["ok"] is False and result["state"] == "accepted"
    assert "action failed" not in str(result["error"])
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "executing"

    monkeypatch.setattr(store, "resolve_pending", real_resolve)
    recovered = approval_execution_recovery.recover_one(approval_id)

    assert recovered is not None and recovered["state"] == "accepted"
    record = store.get_pending(approval_id)
    assert record is not None and record["status"] == "action_outcome_unknown"
    assert graph.sends == 1


def test_legacy_mail_receipt_without_submission_migrates_to_unknown() -> None:
    draft = _draft()
    approval_id = _queued_send(draft)
    _ = store.resolve_pending(approval_id, "executing")
    record = store.get_pending(approval_id)
    assert record is not None
    store.write_action_receipt(approval_id, {
        "version": 1,
        "status": "action_committed",
        "approval_id": approval_id,
        "authority_digest": authority_digest(record),
        "result": json.dumps({"remote_id": "draft-1", "state": "accepted"}),
    })

    result = approval_execution_recovery.recover_one(approval_id)

    assert result is not None
    assert result["ok"] is False and result["state"] == "accepted"
    assert ExecutionJournal(approval_id).load().phase is JournalPhase.ACTION_OUTCOME_UNKNOWN
    migrated = store.get_pending(approval_id)
    assert migrated is not None and migrated["status"] == "action_outcome_unknown"
    assert migrated["mail_recheck_state"] == "accepted"


def test_non_draft_observation_must_still_match_approved_content() -> None:
    graph = Graph202(False, corrupt_sent=True)

    receipt = json.loads(execute_approved_send(_draft(), client=graph))

    assert receipt["state"] == "needs_review"


def test_legacy_sent_receipt_requires_current_remote_observation() -> None:
    graph = Graph202(True)
    draft = _draft()
    receipt = json.loads(execute_approved_send(draft, client=graph))
    receipt["state"] = "sent"
    store._write_json(config.mail_receipts_path(), {draft["content_sha256"]: receipt})

    observed = json.loads(reconcile_approved_send(draft, client=graph))

    assert observed["state"] == "legacy_sent_unverified"
    assert graph.sends == 1


_CHILD = r'''import json, os, pathlib
from birkin import config, store
from birkin.m365_mail import execute_approved_send
class G:
 def __init__(self): self.p=pathlib.Path(os.environ["GRAPH_STATE"])
 def load(self): return json.loads(self.p.read_text()) if self.p.exists() else {"creates":0,"sends":0,"submitted":False}
 def save(self,x): self.p.write_text(json.dumps(x))
 def request(self,m,p,body=None):
  x=self.load()
  if m=="GET" and p.startswith("/me?"): return {"id":"test","userPrincipalName":"a@example.com","mail":"a@example.com"}
  if m=="GET" and p=="/organization?$select=id": return {"value":[{"id":"tenant-a"}]}
  if m=="POST" and p=="/me/messages":
   x["creates"]+=1; x["remote"]={**body,"id":"draft-1","isDraft":True}; self.save(x)
   return {"id":"draft-1"}
  if m=="POST" and p.endswith("/send"):
   if os.environ.get("MAIL_CRASH_POINT")=="attempt_before_post": os._exit(92)
   x["sends"]+=1; x["submitted"]=True; self.save(x)
   if os.environ.get("MAIL_CRASH_POINT")=="post_before_local_state": os._exit(93)
   return {}
  if m=="GET" and p.startswith("/me/messages/draft-1"):
   return {**x["remote"],"isDraft":not x["submitted"],"sentDateTime":"2026-09-06T00:00:00Z" if x["submitted"] else None}
  raise AssertionError((m,p))
orig_write=store._write_json
def write_then_crash(path,value):
 orig_write(path,value)
 if os.environ.get("MAIL_CRASH_POINT")=="draft_stored_before_post" and path==config.mail_receipts_path() and any(isinstance(v,dict) and v.get("state")=="remote_draft_created" for v in value.values()): os._exit(91)
store._write_json=write_then_crash
print(execute_approved_send(json.loads(os.environ["MAIL_PAYLOAD"]), client=G()))
'''


@pytest.mark.parametrize(("point", "expected_sends", "expected_state"), [
    ("draft_stored_before_post", 1, "submitted"),
    ("attempt_before_post", 0, "unknown"),
    ("post_before_local_state", 1, "submitted"),
])
def test_separate_child_crash_never_reposts_ambiguous_attempt(
    tmp_path: Path, point: str, expected_sends: int, expected_state: str,
) -> None:
    draft = _draft()
    graph_state = tmp_path / "graph.json"
    env = {
        **os.environ,
        "BIRKIN_HOME": str(tmp_path),
        "MAIL_CRASH_POINT": point,
        "GRAPH_STATE": str(graph_state),
        "MAIL_PAYLOAD": json.dumps(draft),
    }
    child = subprocess.run([sys.executable, "-c", _CHILD], env=env, check=False)
    assert child.returncode in {91, 92, 93}

    env.pop("MAIL_CRASH_POINT")
    retry = subprocess.run(
        [sys.executable, "-c", _CHILD], env=env, check=True,
        capture_output=True, text=True,
    )
    recovered = json.loads(retry.stdout)
    persisted = json.loads(graph_state.read_text())

    assert persisted["creates"] == 1
    assert persisted["sends"] == expected_sends
    assert recovered["state"] == expected_state
