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
