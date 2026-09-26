from __future__ import annotations

import json
from pathlib import Path

from birkin import approvals
from birkin.m365_connection import status
from birkin.tools import build_registry
from birkin.tools._types import ToolContext


def test_connection_uses_secret_reference_and_distinguishes_states(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})
    proposed = registry.execute("m365_connection_request", {
        "action": "connect", "account_id": "user-1", "account_name": "Ada@Example.com",
        "scopes": ["User.Read", "Mail.Read", "Calendars.Read"], "secret_env": "BIRKIN_M365_TOKEN",
    })
    approval_id = json.loads(proposed.content)["id"]
    approved = approvals.approve(approval_id, approved_by="human:test", approved_via="test")
    assert approved["ok"] is True
    assert status(env={})["state"] == "reauthentication_required"
    monkeypatch.setenv("BIRKIN_M365_TOKEN", "secret-value")
    connected = status(env={"BIRKIN_M365_TOKEN": "secret-value"})
    assert connected["state"] == "verification_required"
    from birkin.m365_connection import apply_approved

    class IdentityGraph:
        def request(self, method, path):
            assert method == "GET"
            if path.startswith("/me?"):
                return {"id": "user-1", "userPrincipalName": "ada@example.com", "mail": "Ada@Example.com"}
            assert path == "/organization?$select=id"
            return {"value": [{"id": "tenant-1"}]}

    monkeypatch.setattr("birkin.m365_graph.graph_client", lambda **_: IdentityGraph())
    from birkin.m365_connection import verified_approval_identity
    assert verified_approval_identity()["tenant_id"] == "tenant-1"
    connected = status(env={"BIRKIN_M365_TOKEN": "secret-value"})
    assert connected["state"] == "connected"
    assert connected["account"]["name"] == "Ada@Example.com"
    assert "secret-value" not in str(connected)

    from birkin.m365_connection import record_sync_result

    record_sync_result("gateway unavailable")
    assert status(env={"BIRKIN_M365_TOKEN": "secret-value"})["state"] == "sync_failed"
    record_sync_result(None)
    previous_generation = connected["generation"]
    record_sync_result("authentication_required")
    assert status(env={"BIRKIN_M365_TOKEN": "secret-value"})["state"] == "reauthentication_required"
    apply_approved({"action": "reauthenticate", "scopes": connected["scopes"]})
    assert status(env={"BIRKIN_M365_TOKEN": "secret-value"})["generation"] != previous_generation
    assert status(env={"BIRKIN_M365_TOKEN": "secret-value"})["state"] == "verification_required"
    assert verified_approval_identity()["tenant_id"] == "tenant-1"
    assert status(env={"BIRKIN_M365_TOKEN": "secret-value"})["state"] == "connected"

    revoked = registry.execute("m365_connection_request", {"action": "revoke"})
    approved = approvals.approve(json.loads(revoked.content)["id"], approved_by="human:test", approved_via="test")
    assert approved["ok"] is True and status(env={"BIRKIN_M365_TOKEN": "secret-value"})["state"] == "revoked"


def test_connection_refuses_write_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin.m365_connection import apply_approved

    try:
        apply_approved({"action": "connect", "account_id": "u", "account_name": "u@example.com", "secret_env": "TOKEN", "scopes": ["Mail.Send"]})
    except ValueError as error:
        assert "delegated scopes" in str(error)
    else:
        raise AssertionError("write scope was accepted")


def test_workspace_snapshot_exposes_account_scope_and_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin.workspace.service import WorkspaceService

    service = WorkspaceService(root=tmp_path / "workspace", session_id="session-1", handlers={})
    office = next(panel for panel in service.snapshot().panels if panel.key == "files_evidence")
    connection = next(item for item in office.items if item["kind"] == "connection")
    assert connection["summary"] == "Microsoft 365 · 연결되지 않음"
    assert connection["status"] == "not_connected"
    assert connection["detail"].startswith("연결되지 않음") and connection["ui_state"] == "idle"

    from birkin.m365_connection import apply_approved

    monkeypatch.setenv("BIRKIN_M365_TOKEN", "secret-value")
    apply_approved({"action": "connect", "account_id": "user-1", "account_name": "Ada@Example.com", "scopes": ["Mail.Read"], "secret_env": "BIRKIN_M365_TOKEN"})
    office = next(panel for panel in service.snapshot().panels if panel.key == "files_evidence")
    connection = next(item for item in office.items if item["kind"] == "connection")
    assert "계정 확인 대기" in connection["detail"] and "verification_required" not in connection["detail"]
    assert connection["ui_state"] == "waiting_dependency"
    assert connection["status"] == "verification_required"


def _connect(tmp_path: Path, monkeypatch, *, remote_id: str = "user-1"):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("BIRKIN_M365_TOKEN", "secret-value")
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})
    proposed = registry.execute("m365_connection_request", {
        "action": "connect", "account_id": "user-1", "account_name": "Ada@Example.com",
        "scopes": ["User.Read", "Mail.Read", "Calendars.Read"], "secret_env": "BIRKIN_M365_TOKEN",
    })
    approved = approvals.approve(json.loads(proposed.content)["id"], approved_by="human:test", approved_via="test")
    assert approved["ok"] is True and status()["state"] == "verification_required"
    paths: list[str] = []

    class FakeGraph:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def request(self, method, path, *_args, **_kwargs):
            assert method == "GET"
            paths.append(path)
            if path.startswith("/me?"):
                return {"id": remote_id, "userPrincipalName": "ada@example.com"}
            if path.startswith("/organization"):
                return {"value": [{"id": "tenant-1"}]}
            if path.startswith("/me/messages"):
                return {"value": [{"id": "m1"}]}
            if path.startswith("/me/calendarView"):
                return {"value": [{"id": "e1"}]}
            if path.startswith("/me/events/"):
                return {"id": "e1", "subject": ""}
            raise AssertionError(path)

    monkeypatch.setattr("birkin.m365_graph.GraphClient", FakeGraph)
    return registry, paths


def test_first_read_after_connect_verifies_account(tmp_path: Path, monkeypatch) -> None:
    registry, paths = _connect(tmp_path, monkeypatch)

    read = registry.execute("m365_mail_read", {})

    assert not read.is_error and json.loads(read.content)["messages"] == [{"id": "m1"}]
    assert [path.split("?")[0] for path in paths] == ["/me", "/organization", "/me/messages"]
    assert status()["state"] == "connected"
    paths.clear()
    calendar = registry.execute("m365_calendar_read", {"start": "2026-09-26T00:00:00+00:00", "end": "2026-09-27T00:00:00+00:00"})
    assert not calendar.is_error and json.loads(calendar.content)["events"] == [{"id": "e1"}]
    assert not any(path.startswith("/me?") for path in paths)


def test_read_refuses_mismatched_account_in_korean(tmp_path: Path, monkeypatch) -> None:
    registry, paths = _connect(tmp_path, monkeypatch, remote_id="someone-else")

    read = registry.execute("m365_mail_read", {})

    assert read.is_error and "계정과 조직을 확인하지 못했습니다" in read.content
    assert not any(path.startswith("/me/messages") for path in paths)
    assert status()["state"] == "verification_required"


def test_meeting_prepare_right_after_connect(tmp_path: Path, monkeypatch) -> None:
    registry, _paths = _connect(tmp_path, monkeypatch)

    prepared = registry.execute("m365_meeting_prepare", {"event_id": "e1", "sources": [{"import_id": "x"}]})

    assert not prepared.is_error and json.loads(prepared.content)["event"]["id"] == "e1"
    assert status()["state"] == "connected"


def test_connect_with_write_scope_is_refused_before_approval(tmp_path: Path, monkeypatch) -> None:
    from birkin import store

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})

    refused = registry.execute("m365_connection_request", {
        "action": "connect", "account_id": "user-1", "account_name": "Ada@Example.com",
        "scopes": ["Mail.Read", "Mail.Send"], "secret_env": "BIRKIN_M365_TOKEN",
    })

    assert refused.is_error
    body = json.loads(refused.content)
    assert body["error_code"] == "write_scope_on_connect" and "읽기 권한" in body["message"]
    assert store.list_pending() == []


def test_revoke_and_reauthenticate_without_connection_are_refused_before_approval(tmp_path: Path, monkeypatch) -> None:
    from birkin import store

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})

    for action in ("revoke", "reauthenticate"):
        refused = registry.execute("m365_connection_request", {"action": action})
        assert refused.is_error and json.loads(refused.content)["error_code"] == "not_connected", action
    assert store.list_pending() == []


def test_reauthenticate_may_add_write_scope(tmp_path: Path, monkeypatch) -> None:
    registry, _paths = _connect(tmp_path, monkeypatch)

    queued = registry.execute("m365_connection_request", {"action": "reauthenticate", "scopes": ["Mail.Read", "Mail.Send"]})

    assert not queued.is_error
    approved = approvals.approve(json.loads(queued.content)["id"], approved_by="human:test", approved_via="test")
    assert approved["ok"] is True and "Mail.Send" in status()["scopes"]


def test_connect_schema_offers_read_scopes_only(tmp_path: Path) -> None:
    from birkin.m365_connection import READ_SCOPES

    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})
    spec = next(item for item in registry.specs() if item["name"] == "m365_connection_request")
    connect = spec["input_schema"]["allOf"][0]
    assert connect["if"]["properties"]["action"]["const"] == "connect"
    assert connect["then"]["properties"]["scopes"]["items"]["enum"] == sorted(READ_SCOPES)


def test_connection_approval_description_is_korean(tmp_path: Path, monkeypatch) -> None:
    from birkin import store

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})
    _ = registry.execute("m365_connection_request", {
        "action": "connect", "account_id": "user-1", "account_name": "Ada@Example.com",
        "scopes": ["Mail.Read"], "secret_env": "BIRKIN_M365_TOKEN",
    })

    description = store.list_pending()[0]["description"]
    assert "Microsoft 365 연결" in description and "Ada@Example.com" in description
    assert "connect " not in description


def test_graph_client_state_error_is_korean(tmp_path: Path, monkeypatch) -> None:
    import pytest

    from birkin.m365_connection import apply_approved
    from birkin.m365_graph import GraphError, graph_client

    _connect(tmp_path, monkeypatch)
    apply_approved({"action": "revoke"})

    with pytest.raises(GraphError) as raised:
        graph_client()
    assert "연결 해제됨" in str(raised.value) and "revoked" not in str(raised.value)


def test_status_tool_adds_korean_label(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})

    body = json.loads(registry.execute("m365_connection_status", {}).content)

    assert body["state"] == "not_connected" and body["state_label"] == "연결되지 않음"


def _busy_then_graph(monkeypatch, *, remote_id: str) -> list[str]:
    """Real GraphClient: the first /me is a transient 503, later /me answers as remote_id."""
    import io
    import urllib.error

    from birkin.m365_graph import ORIGIN

    paths: list[str] = []
    busy = [True]

    class Response(io.BytesIO):
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

    def opener(request, *, timeout):
        path = request.full_url.removeprefix(ORIGIN).split("?")[0]
        paths.append(path)
        if path == "/me" and busy:
            busy.clear()
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)
        bodies = {
            "/me": {"id": remote_id, "userPrincipalName": "ada@example.com"},
            "/organization": {"value": [{"id": "tenant-1"}]},
            "/me/messages": {"value": [{"id": "m1"}]},
            "/me/calendarView": {"value": [{"id": "e1"}]},
        }
        return Response(json.dumps(bodies[path]).encode())

    monkeypatch.setattr("birkin.m365_graph.open_no_redirect", opener)
    return paths


def test_transient_failure_during_verification_never_reads_unverified(tmp_path: Path, monkeypatch) -> None:
    from birkin.m365_connection import apply_approved

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("BIRKIN_M365_TOKEN", "secret-value")
    apply_approved({"action": "connect", "account_id": "user-1", "account_name": "Ada@Example.com", "scopes": ["Mail.Read", "Calendars.Read"], "secret_env": "BIRKIN_M365_TOKEN"})
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})
    paths = _busy_then_graph(monkeypatch, remote_id="someone-else")

    first = registry.execute("m365_mail_read", {})
    assert first.is_error and status()["state"] == "sync_failed"
    second = registry.execute("m365_mail_read", {})
    calendar = registry.execute("m365_calendar_read", {"start": "2026-09-26T00:00:00+00:00", "end": "2026-09-27T00:00:00+00:00"})

    assert second.is_error and "계정과 조직을 확인하지 못했습니다" in second.content
    assert calendar.is_error and "계정과 조직을 확인하지 못했습니다" in calendar.content
    assert not {"/me/messages", "/me/calendarView"} & set(paths)
    assert status()["state"] == "verification_required"


def test_transient_failure_during_verification_recovers_on_next_read(tmp_path: Path, monkeypatch) -> None:
    from birkin.m365_connection import apply_approved

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("BIRKIN_M365_TOKEN", "secret-value")
    apply_approved({"action": "connect", "account_id": "user-1", "account_name": "Ada@Example.com", "scopes": ["Mail.Read"], "secret_env": "BIRKIN_M365_TOKEN"})
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"connections"})
    paths = _busy_then_graph(monkeypatch, remote_id="user-1")

    assert registry.execute("m365_mail_read", {}).is_error
    second = registry.execute("m365_mail_read", {})

    assert not second.is_error and json.loads(second.content)["messages"] == [{"id": "m1"}]
    assert paths == ["/me", "/me", "/organization", "/me/messages"]
    assert status()["state"] == "connected"
