"""Independent review checks for Office boundary failures."""

import pytest

from birkin.m365_calendar import MAX_CALENDAR_PAGES, _graph_event, calendar_view


class CalendarResponse:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return self.response


@pytest.mark.parametrize("response", [{}, {"value": [None]}, {"value": [{}]}, {"value": [{"id": ""}]}])
def test_review_calendar_rejects_incomplete_event_identity(response):
    with pytest.raises(ValueError):
        calendar_view("2026-09-07T09:00:00+09:00", "2026-09-07T10:00:00+09:00", client=CalendarResponse(response))


def test_review_calendar_paging_stops_without_following_foreign_origin():
    foreign = CalendarResponse({"value": [], "@odata.nextLink": "https://graph.microsoft.com.evil.example/v1.0/me/calendarView"})
    with pytest.raises(ValueError):
        calendar_view("2026-09-07T09:00:00+09:00", "2026-09-07T10:00:00+09:00", client=foreign)
    assert foreign.calls == 1
    endless = CalendarResponse({"value": [], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/calendarView?$skip=1"})
    with pytest.raises(ValueError):
        calendar_view("2026-09-07T09:00:00+09:00", "2026-09-07T10:00:00+09:00", client=endless)
    assert endless.calls == MAX_CALENDAR_PAGES


def test_review_all_day_dst_preserves_dates_in_a_23_hour_day():
    body = _graph_event({
        "timezone": "America/New_York", "is_all_day": True,
        "start": "2026-03-08T00:00:00-05:00", "end": "2026-03-09T00:00:00-04:00",
        "subject": "휴일", "attendees": [], "location": "", "body": "",
    })
    assert body["start"] == {"dateTime": "2026-03-08T00:00:00", "timeZone": "America/New_York"}
    assert body["end"] == {"dateTime": "2026-03-09T00:00:00", "timeZone": "America/New_York"}


def test_review_batch_pending_receipt_is_not_a_completed_export(tmp_path, monkeypatch):
    import json

    from birkin import store
    from birkin.office import batch
    from birkin.office.coordinator import OfficeCaller

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    source = tmp_path / "source.docx"
    source.write_bytes(b"test source")
    request = {"source": {"uri": str(source)}, "destination": str(tmp_path / "out.docx")}
    plan = {"job_id": "pending-job", "allowlist_root": str(tmp_path)}
    batch_id = "a" * 32
    store._write_json(batch._path(batch_id), {
        "batch_id": batch_id, "requests": [request], "plans": [plan],
        "results": [{"index": 0, "status": "pending"}],
    })
    monkeypatch.setattr(batch, "approved_office_receipt", lambda _: json.dumps({
        "job_id": "pending-job", "state": "approval_requested", "export": None,
    }))
    resumed = batch.prepare([], OfficeCaller(tmp_path, "test"), retry_of=batch_id)
    assert resumed["plans"] == [plan]
    assert store._read_json(batch._path(batch_id), {})["results"][0]["status"] != "succeeded"


def test_review_legacy_skip_and_host_local_schedule_keep_their_clock(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from birkin import cron

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    job = cron.add_job(name="review legacy", action_type="prompt", value="test", schedule="09:00")
    assert cron.skip_next(job["id"])
    schedule = {"kind": "daily", "hour": 9, "minute": 0, "timezone": "Asia/Seoul"}
    host_local = datetime(2026, 9, 7, 8)
    same_instant = host_local.astimezone(timezone.utc)
    assert cron.compute_next_run(schedule, now=host_local) == cron.compute_next_run(schedule, now=same_instant)


@pytest.mark.parametrize("extra", [
    {"bccRecipients": [{"emailAddress": {"address": "unapproved@example.com"}}]},
    {"attachments": [{"@odata.type": "#microsoft.graph.referenceAttachment", "name": "unapproved"}]},
])
def test_review_mail_retry_rejects_hidden_recipient_or_extra_attachment(extra):
    from birkin.m365_mail import _remote_matches

    draft = {"subject": "검토", "body": "확인", "to": ["approved@example.com"], "cc": [], "attachments": []}
    remote = {
        "subject": "검토", "body": {"content": "확인"},
        "toRecipients": [{"emailAddress": {"address": "approved@example.com"}}],
        "ccRecipients": [], "bccRecipients": [], "attachments": [],
        **extra,
    }
    assert not _remote_matches(draft, remote)


def test_review_sender_mismatch_stops_before_remote_mutation(tmp_path, monkeypatch):
    from birkin import config, store
    from birkin.m365_connection import approval_identity
    from birkin.m365_mail import create_local_draft, execute_approved_send

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    store._write_json(config.connections_path(), {"microsoft-365": {
        "account_id": "account-b", "account_name": "b@example.com", "generation": "generation-b",
        "verified_identity": {"id": "account-b", "name": "b@example.com", "generation": "generation-b", "tenant_id": "tenant-b"},
    }})
    draft = create_local_draft({
        "action": "new", "from_account": "a@example.com", "to": ["recipient@example.com"],
        "subject": "검토", "body": "확인", "attachments": [], "connection_identity": approval_identity(),
    })

    class AccountB:
        def request(self, method, path, *args, **kwargs):
            assert method == "GET", "mismatched sender must never mutate Graph"
            if path == "/organization?$select=id":
                return {"value": [{"id": "tenant-b"}]}
            assert path.startswith("/me?")
            return {"id": "account-b", "userPrincipalName": "b@example.com", "mail": "b@example.com"}

    with pytest.raises(ValueError, match="sender"):
        execute_approved_send(draft, client=AccountB())


def test_review_named_reviewer_can_read_after_account_switch(tmp_path, monkeypatch):
    from birkin import config, store
    from birkin.team_review import list_review

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    store._write_json(config.connections_path(), {"microsoft-365": {
        "account_id": "reviewer-id", "account_name": "reviewer@example.com", "generation": "reviewer-generation",
    }})
    store._write_json(config.team_reviews_path(), {"review-1": {
        "id": "review-1", "proposer": "owner@example.com", "reviewers": ["REVIEWER@example.com"],
        "connection_identity": {"account_id": "owner-id", "account_name": "owner@example.com", "generation": "owner-generation", "tenant_id": None},
    }})

    class Reviewer:
        def request(self, method, path, *args, **kwargs):
            if method == "GET" and path == "/organization?$select=id":
                return {"value": [{"id": "reviewer-tenant"}]}
            assert method == "GET" and path.startswith("/me?")
            return {"id": "reviewer-id", "mail": "reviewer@example.com", "userPrincipalName": "reviewer@example.com"}

    assert list_review("review-1", client=Reviewer())["id"] == "review-1"


@pytest.mark.parametrize("operation", ["mail", "calendar", "share"])
@pytest.mark.parametrize("legacy", [False, True])
def test_review_tenant_binding_stops_every_external_mutation(tmp_path, monkeypatch, operation, legacy):
    from birkin import config, m365_calendar, m365_mail, store, team_review

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    identity = {"account_id": "same-account", "account_name": "same@example.com", "generation": "same-generation", "tenant_id": "tenant-a"}
    store._write_json(config.connections_path(), {"microsoft-365": {
        **identity,
        "verified_identity": {"id": identity["account_id"], "name": identity["account_name"], "generation": identity["generation"], "tenant_id": "tenant-a"},
    }})
    approved = {**identity, "tenant_id": None} if legacy else identity
    calls = []

    class ChangedTenant:
        def request(self, method, path, *args, **kwargs):
            calls.append((method, path))
            assert method == "GET", "tenant mismatch must stop before any external mutation"
            if path.startswith("/me?"):
                return {"id": "same-account", "userPrincipalName": "same@example.com"}
            assert path == "/organization?$select=id"
            return {"value": [{"id": "tenant-b"}]}

    # Keep each production execution path and its real shared identity guard.
    # Draft loading is isolated because this test targets the mutation boundary.
    monkeypatch.setattr(m365_mail, "_load_bound", lambda *_: {"connection_identity": approved})
    monkeypatch.setattr(m365_calendar, "get_local_event", lambda *_: {"connection_identity": approved})
    monkeypatch.setattr(team_review, "get_handoff", lambda *_: {"connection_identity": approved})
    execute = {
        "mail": lambda: m365_mail.execute_approved_send({}, client=ChangedTenant()),
        "calendar": lambda: m365_calendar.execute_approved_event({}, client=ChangedTenant()),
        "share": lambda: team_review.execute_share({}, approval_id=None, client=ChangedTenant()),
    }[operation]
    with pytest.raises(ValueError):
        execute()
    assert all(method == "GET" for method, _ in calls)
    if not legacy:
        assert ("GET", "/organization?$select=id") in calls


def test_review_connection_revoked_during_identity_check_is_not_revalidated(tmp_path, monkeypatch):
    from birkin import config, store
    from birkin.m365_connection import apply_approved, verify_approval_identity

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    identity = {"account_id": "account", "account_name": "a@example.com", "generation": "generation", "tenant_id": "tenant"}
    store._write_json(config.connections_path(), {"microsoft-365": {
        **identity,
        "verified_identity": {"id": "account", "name": "a@example.com", "generation": "generation", "tenant_id": "tenant"},
    }})

    class RevokedDuringRead:
        def request(self, method, path):
            assert method == "GET"
            if path.startswith("/me?"):
                return {"id": "account", "mail": "a@example.com"}
            assert path == "/organization?$select=id"
            apply_approved({"action": "revoke"})
            return {"value": [{"id": "tenant"}]}

    with pytest.raises(ValueError):
        verify_approval_identity(identity, RevokedDuringRead())
    assert store._read_json(config.connections_path(), {})["microsoft-365"]["revoked"] is True


@pytest.mark.parametrize("code,state,error", [
    (401, "reauthentication_required", "authentication_required"),
    (403, "sync_failed", "http_403"),
    (503, "sync_failed", "http_503"),
])
def test_review_graph_failures_update_connection_health(tmp_path, monkeypatch, code, state, error):
    import urllib.error

    from birkin import config, store
    from birkin.m365_connection import status
    from birkin.m365_graph import GraphClient, GraphError

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("REVIEW_M365_TOKEN", "synthetic-token")
    store._write_json(config.connections_path(), {"microsoft-365": {
        "account_id": "account", "account_name": "a@example.com", "generation": "generation",
        "secret_env": "REVIEW_M365_TOKEN",
        "verified_identity": {"id": "account", "name": "a@example.com", "generation": "generation", "tenant_id": "tenant"},
    }})

    def unavailable(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, code, "synthetic failure", {}, None)

    monkeypatch.setattr("birkin.m365_graph.open_no_redirect", unavailable)
    with pytest.raises(GraphError, match=str(code)):
        GraphClient("synthetic-token", track_health=True).request("GET", "/organization?$select=id")
    connection = status()
    assert connection["state"] == state
    assert connection["last_sync_error"] == error


@pytest.mark.parametrize("bad_calendar", [False, True])
def test_review_briefing_recovers_transient_health_without_losing_other_sections(tmp_path, monkeypatch, bad_calendar):
    from birkin import daily_briefing

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setattr(daily_briefing, "connection_status", lambda: {"state": "sync_failed"})
    monkeypatch.setattr(daily_briefing, "list_messages", lambda **_: {"messages": [{"id": "mail-ok"}]})

    def calendar(*args, **kwargs):
        if bad_calendar:
            raise ValueError("Microsoft Graph calendar page was invalid")
        return {"events": [{"id": "event-ok"}]}

    monkeypatch.setattr(daily_briefing, "calendar_view", calendar)
    report = daily_briefing.generate({"id": "review-briefing", "value": "{}"})
    assert report["unread_mail"] == [{"id": "mail-ok"}]
    if bad_calendar:
        assert report["calendar"] == []
        assert any(item["source"] == "calendar" for item in report["unreadable_connections"])
    else:
        assert report["calendar"] == [{"id": "event-ok"}]


def test_review_native_work_edit_waits_for_approval_and_keeps_future_item(tmp_path, monkeypatch):
    import json

    from birkin import approvals, work_items
    from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    item = json.loads(work_items.apply_approved({
        "action": "create", "title": "승인 후 수정할 업무", "assignee": "민지", "due_date": "2050-01-01",
    }))["items"][0]
    adapter = RuntimeWorkspaceAdapter("review-work", lambda *_: None, workspace_root=tmp_path)
    queued = adapter.handlers()["work_item.request"]({
        "action": "update", "id": item["id"], "assignee": "수진", "due_date": "2050-01-02",
    })
    before = work_items.grouped()["upcoming"][0]
    assert before["assignee"] == "민지" and before["due_date"] == "2050-01-01"
    assert approvals.approve(queued["id"], approved_by="human:review", approved_via="test")["ok"]
    after = work_items.grouped()["upcoming"][0]
    assert after["assignee"] == "수진" and after["due_date"] == "2050-01-02"


def test_review_native_source_open_emits_the_office_projection(tmp_path, monkeypatch):
    from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    emitted = []
    adapter = RuntimeWorkspaceAdapter("review-open", lambda kind, payload: emitted.append((kind, payload)), workspace_root=tmp_path)
    authority = adapter.surface_authority.office
    artifact = authority.service.create_document(format="docx", content={"paragraphs": ["원본"]}, output_name="review.docx")["draft_artifact"]
    authority.open({"artifact": artifact})
    result = adapter.handlers()["work_item.open_source"]({"artifact_uri": artifact["uri"]})
    assert result["receipt"]["source_sha256"] == artifact["content_hash"]
    assert any(kind == "office.updated" and payload["result"] == result for kind, payload in emitted)
