from __future__ import annotations

import http.client
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer

import pytest

from birkin import agentruns, approvals, config, store, summon
from birkin.web import server as web_server
from tests.local_http_support import local_http_timeout


@pytest.fixture
def srv():
    httpd = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], web_server._TOKEN
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def remote_srv(monkeypatch):
    class ForcedRemoteHTTPServer(HTTPServer):
        def get_request(self):
            request, address = super().get_request()
            return request, ("198.51.100.23", address[1])

    cfg = {
        **config.DEFAULT_CONFIG,
        "web_remote_access": True,
        "web_external_url": "https://console.example",
    }
    monkeypatch.setattr(web_server.config, "load_config", lambda: cfg)
    httpd = ForcedRemoteHTTPServer(("127.0.0.1", 0), web_server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            httpd.server_address[1],
            web_server._TOKEN,
            web_server.listener_bootstrap_nonce(httpd),
        )
    finally:
        httpd.shutdown()
        httpd.server_close()


def request(srv, method: str, path: str, payload=None, *, token=True,
            host="127.0.0.1", client_id: str | None = None):
    port, capability = srv[:2]
    headers = {"Host": host}
    if token:
        headers["X-Birkin-Token"] = capability
    if client_id is not None:
        headers["X-Birkin-Browser-Client"] = client_id
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    try:
        parsed = json.loads(data) if data else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = data.decode("utf-8", "replace")
    return response.status, parsed


def test_run_listing_shape_and_detail_marks_waiting_approval(srv):
    run = agentruns.register_run("deploy the release")
    agentruns.progress(run["id"], "prepared patch")
    store.add_pending(
        category="shell", title="publish", description="run publisher",
        payload={"command": "publish", "run_id": run["id"]},
        origin=f"agent:{run['id']}",
    )

    status, payload = request(srv, "GET", "/api/agent-runs")
    assert status == 200
    listed = payload["runs"][0]
    assert set(listed) >= {
        "id", "task", "status", "ui_state", "terminal", "started_at",
        "last_heartbeat", "heartbeat_age", "parent_id", "pending_approvals",
        "control_state", "controls",
    }
    assert listed["status"] == "waiting-approval"
    assert listed["ui_state"] == "waiting_human"
    assert listed["terminal"] is False
    assert listed["pending_approvals"] == 1

    status, detail = request(srv, "GET", f"/api/agent-runs/{run['id']}")
    assert status == 200
    assert detail["events"][0]["text"] == "prepared patch"
    assert detail["approvals"][0]["category"] == "shell"


@pytest.mark.parametrize("path", [
    "/api/agent-runs", "/api/agent-runs/000000000000",
    "/api/actions/000000000000/receipt", "/api/agents",
])
def test_console_reads_require_capability(srv, path):
    assert request(srv, "GET", path, token=False)[0] == 403


def _run_summary(srv, run_id: str) -> dict:
    status, payload = request(srv, "GET", "/api/agent-runs")
    assert status == 200
    return next(row for row in payload["runs"] if row["id"] == run_id)


def _age(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def test_run_controls_follow_durable_transitions(srv):
    run = agentruns.register_run("long task")
    endpoint = f"/api/agent-runs/{run['id']}/control"
    listed = _run_summary(srv, run["id"])
    assert listed["controls"] == ["steer", "abort"]
    assert listed["control_state"] == "active"

    status, aborted = request(srv, "POST", endpoint, {"action": "abort"})
    assert status == 200
    assert aborted["controls"] == ["resume"]
    assert aborted["control_state"] == "blocked"

    # A pending approval changes the display status, not what may be sent.
    store.add_pending(
        category="shell", title="publish", description="",
        payload={"command": "publish"}, origin=f"agent:{run['id']}",
    )
    status, detail = request(srv, "GET", f"/api/agent-runs/{run['id']}")
    assert status == 200
    assert detail["status"] == "waiting-approval"
    assert detail["controls"] == ["resume"]
    status, resumed = request(srv, "POST", endpoint, {"action": "resume"})
    assert status == 200
    assert resumed["controls"] == ["steer", "abort"]

    agentruns.finish_run(run["id"], "done", "ok")
    assert _run_summary(srv, run["id"])["controls"] == []


def test_stalled_run_detail_matches_listing(srv):
    run = agentruns.register_run("silent worker")
    agentruns._update(run["id"], {"last_heartbeat": _age(600)})

    listed = _run_summary(srv, run["id"])
    status, detail = request(srv, "GET", f"/api/agent-runs/{run['id']}")

    assert status == 200
    for row in (listed, detail):
        assert row["runtime_status"] == "stale"
        assert row["terminal"] is True
        assert row["ui_state"] == "unknown"
        assert row["controls"] == []


def _write_agent(name: str, body: str) -> None:
    directory = summon.agents_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(body, encoding="utf-8")


_MY_BOT = (
    "---\nname: my-bot\ntitle: 내 봇\ndescription: 테스트용 에이전트\n"
    "tools: [files]\n---\nSECRET-INSTRUCTION-TEXT\n"
)


def test_run_summary_names_agent_and_elapsed(srv):
    _write_agent("my-bot", _MY_BOT)
    builtin = agentruns.register_run("시트 분석", agent="sheet-analyst")
    user = agentruns.register_run("내 작업", agent="my-bot")
    ghost = agentruns.register_run("사라진 에이전트", agent="ghost")
    plain = agentruns.register_run("일반 실행")
    agentruns._update(builtin["id"], {"started_at": _age(300)})
    agentruns.finish_run(builtin["id"], "done", "결론")

    listed = _run_summary(srv, builtin["id"])
    assert listed["agent_title"] == "스프레드시트 분석가"
    assert listed["agent_source"] == "builtin"
    assert 298 <= listed["elapsed_seconds"] <= 305
    assert _run_summary(srv, user["id"])["agent_source"] == "user"
    assert _run_summary(srv, user["id"])["agent_title"] == "내 봇"
    assert _run_summary(srv, ghost["id"])["agent_title"] is None
    unnamed = _run_summary(srv, plain["id"])
    assert unnamed["agent"] is None and unnamed["agent_title"] is None
    status, detail = request(srv, "GET", f"/api/agent-runs/{builtin['id']}")
    assert status == 200 and detail["agent_title"] == "스프레드시트 분석가"


def test_approvals_listing_names_raising_agent_run(srv):
    run = agentruns.register_run("시트 분석", agent="sheet-analyst")
    with agentruns._run_scope(run["id"]):
        raised = store.add_pending(
            category="shell", title="export", description="",
            payload={"command": "export"},
        )
    stray = store.add_pending(
        category="shell", title="stray", description="",
        payload={"command": "x", "run_id": "ffffffffffff"},
    )
    plain = store.add_pending(
        category="shell", title="plain", description="", payload={"command": "y"})

    status, items = request(srv, "GET", "/api/approvals")

    assert status == 200
    by_id = {item["id"]: item for item in items}
    assert by_id[raised["id"]]["agent_run"] == {
        "id": run["id"],
        "task": "시트 분석",
        "agent": "sheet-analyst",
        "agent_title": "스프레드시트 분석가",
        "agent_source": "builtin",
    }
    assert "agent_run" not in by_id[stray["id"]]
    assert "agent_run" not in by_id[plain["id"]]
    assert by_id[plain["id"]]["category_label"] == "Shell 명령"
    assert by_id[plain["id"]]["target"] == "y"
    assert by_id[plain["id"]]["needs_answers"] is False


def test_agent_roster_lists_specialists_without_internals(srv):
    _write_agent("my-bot", _MY_BOT)
    _write_agent("broken", "---\nname: broken\n---\n")

    port, capability = srv
    conn = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    conn.request("GET", "/api/agents", headers={
        "Host": "127.0.0.1", "X-Birkin-Token": capability})
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    conn.close()

    assert response.status == 200
    payload = json.loads(body)
    names = [agent["name"] for agent in payload["agents"]]
    builtins = [spec.name for spec in summon.BUILTIN_AGENTS]
    assert names == sorted(builtins) + ["my-bot"]
    assert payload["rejected_count"] == 1
    assert {agent["source"] for agent in payload["agents"][:-1]} == {"builtin"}
    assert payload["agents"][-1]["source"] == "user"
    for agent in payload["agents"]:
        assert set(agent) == {"name", "title", "description", "source", "max_turns"}
    assert "SECRET-INSTRUCTION-TEXT" not in body
    assert str(summon.agents_dir()) not in body


def test_agent_roster_rejects_cross_site_cookie_read(srv):
    port, capability = srv
    conn = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    conn.request("GET", "/api/agents", headers={
        "Host": "127.0.0.1",
        "Cookie": f"{web_server._CAPABILITY_COOKIE}={capability}",
        "Sec-Fetch-Site": "cross-site",
    })
    response = conn.getresponse()
    response.read()
    conn.close()

    assert response.status == 403


def test_approve_reject_transitions_and_action_receipt(srv, monkeypatch):
    monkeypatch.setattr(
        approvals, "execute_action", lambda category, payload: "exit 0: shipped")
    approved = store.add_pending(
        category="shell", title="ship", description="", payload={"command": "ship"})
    rejected = store.add_pending(
        category="cron", title="later", description="", payload={"name": "later"})

    assert request(srv, "POST", "/api/approvals", {
        "id": approved["id"], "action": "approve"}, client_id="browser-1") == (
            200, {"ok": True, "result": "exit 0: shipped"})
    approved_record = store.get_pending(approved["id"])
    assert approved_record is not None
    assert approved_record["status"] == "approved"
    assert approved_record["approved_by"] == "principal:web:authenticated-capability"
    assert approved_record["approved_via"] == "web:dashboard"

    status, receipt = request(
        srv, "GET", f"/api/actions/{approved['id']}/receipt")
    assert status == 200
    assert receipt == {
        "id": approved["id"], "category": "shell", "status": "approved",
        "executed_at": store.get_pending(approved["id"])["resolved_at"],
        "receipt": "exit 0: shipped",
    }

    assert request(srv, "POST", "/api/approvals", {
        "id": rejected["id"], "action": "reject"}, client_id="browser-1") == (
            200,
            {"ok": True},
        )
    rejected_record = store.get_pending(rejected["id"])
    assert rejected_record is not None
    assert rejected_record["status"] == "rejected"
    assert rejected_record["rejected_by"] == "principal:web:authenticated-capability"
    assert rejected_record["rejected_via"] == "web:dashboard"
    assert request(srv, "GET", f"/api/actions/{rejected['id']}/receipt")[0] == 409


def test_steer_abort_resume_state_machine(srv):
    run = agentruns.register_run("long task")
    endpoint = f"/api/agent-runs/{run['id']}/control"

    status, steered = request(srv, "POST", endpoint, {
        "action": "steer", "text": "focus on tests"})
    assert status == 200 and steered["status"] == "running"
    assert agentruns.drain_messages(run["id"]) == ["focus on tests"]

    status, aborted = request(srv, "POST", endpoint, {"action": "abort"})
    assert status == 200 and aborted["status"] == "blocked"
    assert request(srv, "POST", endpoint, {"action": "abort"})[0] == 409
    assert request(srv, "POST", endpoint, {
        "action": "steer", "text": "too early"})[0] == 409

    status, resumed = request(srv, "POST", endpoint, {"action": "resume"})
    assert status == 200 and resumed["status"] == "running"
    assert request(srv, "POST", endpoint, {"action": "resume"})[0] == 409


def test_remote_access_is_opt_in_and_every_remote_request_is_authenticated(
        remote_srv, monkeypatch):
    monkeypatch.setattr(web_server.config, "load_config", lambda: {
        **config.DEFAULT_CONFIG, "web_remote_access": False})
    assert request(
        remote_srv, "GET", "/", token=False, host="console.example"
    )[0] == 403

    monkeypatch.setattr(web_server.config, "load_config", lambda: {
        **config.DEFAULT_CONFIG, "web_remote_access": True})
    assert request(
        remote_srv, "GET", "/", token=False, host="console.example"
    )[0] == 403
    assert request(
        remote_srv, "GET", "/", token=True, host="console.example"
    )[0] == 200


def test_remote_secret_bootstrap_mints_capability_cookie(
        remote_srv, monkeypatch):
    monkeypatch.setattr(web_server.config, "load_config", lambda: {
        **config.DEFAULT_CONFIG, "web_remote_access": True})
    _, _, bootstrap_nonce = remote_srv

    status, payload = request(
        remote_srv,
        "GET",
        f"/_bootstrap/{bootstrap_nonce}",
        token=False,
        host="console.example",
    )

    assert status == 303
    assert payload is None


def test_remote_process_capability_is_not_a_bootstrap_url(
        remote_srv, monkeypatch):
    monkeypatch.setattr(web_server.config, "load_config", lambda: {
        **config.DEFAULT_CONFIG, "web_remote_access": True})
    _, capability, _ = remote_srv

    status, _ = request(
        remote_srv,
        "GET",
        f"/_bootstrap/{capability}",
        token=False,
        host="console.example",
    )

    assert status == 403


def test_loopback_process_capability_is_not_a_bootstrap_url(srv):
    _, capability = srv

    status, _ = request(
        srv,
        "GET",
        f"/_bootstrap/{capability}",
        token=False,
    )

    assert status == 403


def test_dashboard_answer_resumes_moirai_wait_over_http(srv, tmp_path):
    """The HTTP handler runs on a server thread; the answer must resume the
    workflow there instead of killing it at the checkpoint."""
    from birkin import moirai
    from birkin.moirai import journal

    path = tmp_path / "wait_for_input.py"
    path.write_text(
        '''
meta = {"name": "wait-for-input", "roles": {}}

def main(m):
    supplied = m.request_answers(
        step_id="deploy-target",
        title="Deploy release",
        description="Choose the deployment target.",
        questions=[{
            "id": "choice",
            "text": "Continue?",
            "options": [{"value": "yes", "label": "Yes"}],
        }],
    )
    return {"input": supplied}
''',
        encoding="utf-8",
    )
    outcome = moirai.run_script(moirai.load_script(path), cfg={})
    assert outcome["status"] == "waiting_input"
    record = store.list_pending()[0]

    status, payload = request(srv, "POST", "/api/approvals", {
        "id": record["id"],
        "action": "answer",
        "answers": {"choice": "yes"},
        "resume_token": record["resume_token"],
        "question_digest": record["question_digest"],
        "input_schema_version": 1,
        "previous_state_digest": record["previous_state_digest"],
    }, client_id="browser-1")

    assert status == 200, payload
    assert payload["continuation"]["resume_run_id"]
    wait = journal.get_input_wait(record["id"])
    assert wait is not None
    assert wait["state"] == "resumed"
