"""Authenticated HTTP contracts for the shared web workspace backend."""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Callable, Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest

from birkin.web import server as web_server
from birkin.workspace import WorkspaceHub
from birkin.workspace import approval_authority
from script.qa import workspace_web_e2e
from tests.local_http_support import local_http_timeout

EXPECTED_PANEL_KEYS = (
    "tasks_runs",
    "approvals",
    "files_evidence",
    "sessions_history",
    "activity_logs",
    "cron",
    "memory_skills",
    "checkpoints_restore",
    "computer_use",
    "settings_status",
)
HTML_PATH = (
    Path(__file__).resolve().parents[1]
    / "birkin"
    / "web"
    / "static"
    / "index.html"
)


def _request(
    port: int,
    method: str,
    path: str,
    *,
    token: str | None = None,
    host: str = "127.0.0.1",
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    headers = {"Host": host}
    encoded = None
    if token is not None:
        headers["X-Birkin-Token"] = token
    if body is not None:
        encoded = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(encoded))
    conn = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    conn.request(method, path, body=encoded, headers=headers)
    response = conn.getresponse()
    payload = response.read()
    result = response.status, dict(response.getheaders()), payload
    conn.close()
    return result


def _json(body: bytes) -> dict[str, object]:
    decoded = cast(object, json.loads(body))
    assert isinstance(decoded, dict)
    return cast(dict[str, object], decoded)


def _sse_events(body: bytes) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in body.decode("utf-8").strip().split("\n\n"):
        data = [
            line.removeprefix("data: ")
            for line in block.splitlines()
            if line.startswith("data: ")
        ]
        if not data:
            continue
        raw = cast(object, json.loads("\n".join(data)))
        assert isinstance(raw, dict)
        events.append(cast(dict[str, object], raw))
    return events


@pytest.fixture
def workspace_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[int, str, str]]:
    def chat_send(payload: dict[str, object]) -> dict[str, object]:
        return {
            "reply": f"echo:{payload.get('text', '')}",
        }

    def interrupt(_payload: dict[str, object]) -> dict[str, object]:
        return {"interrupted": True}

    def resume(_payload: dict[str, object]) -> dict[str, object]:
        return {"resumed": True}

    handlers: dict[
        str,
        Callable[[dict[str, object]], dict[str, object]],
    ] = {
        "chat.send": chat_send,
        "chat.interrupt": interrupt,
        "chat.resume": resume,
    }
    monkeypatch.setattr(web_server, "_workspace_root", tmp_path, raising=False)
    monkeypatch.setattr(
        web_server,
        "_workspace_handlers",
        handlers,
        raising=False,
    )
    monkeypatch.setattr(web_server, "_workspace_hub", None, raising=False)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.Handler)
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            port,
            web_server.capability_token(),
            web_server.listener_bootstrap_nonce(httpd),
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        hub: object = getattr(web_server, "_workspace_hub", None)
        if isinstance(hub, WorkspaceHub):
            hub.close()


def _create_session(port: int, token: str) -> str:
    code, _, body = _request(
        port,
        "POST",
        "/api/workspace/sessions",
        token=token,
        body={"session_id": "shared-session"},
    )
    assert code == 201
    payload = _json(body)
    session_id = payload.get("session_id")
    assert session_id == "shared-session"
    return str(session_id)


def _command(
    command_id: str,
    *,
    expected_cursor: int,
    command_type: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "command_id": command_id,
        "expected_cursor": expected_cursor,
        "type": command_type,
        "payload": payload,
        "client_context": {"surface": "web", "view_id": "browser-1"},
    }


def _web_approval_payload(
    approval_id: str,
    decision: str,
) -> dict[str, object]:
    source = HTML_PATH.read_text(encoding="utf-8")
    match = re.search(
        r'await sendCommand\("approval\.answer", \{(?P<body>.*?)\n\s*\}\);',
        source,
        re.DOTALL,
    )
    assert match is not None
    keys = cast(
        list[str],
        re.findall(
            r"^\s*([a-z_]+)(?::[^,]+)?,\s*$",
            match.group("body"),
            re.MULTILINE,
        ),
    )
    values: dict[str, object] = {
        "approval_id": approval_id,
        "decision": decision,
        "detail_fields": [
            "expected-impact",
            "rejection-result",
            "related-evidence",
        ],
    }
    return {key: values[key] for key in keys}


def test_workspace_routes_require_capability_before_lookup(
    workspace_server: tuple[int, str, str],
) -> None:
    port, token, _ = workspace_server
    assert _request(port, "GET", "/api/workspace/sessions")[0] == 403
    assert _request(
        port,
        "GET",
        "/api/workspace/sessions/not-found/snapshot",
    )[0] == 403
    assert _request(
        port,
        "GET",
        "/api/workspace/sessions",
        token=token,
        host="evil.example",
    )[0] == 403


def test_create_session_snapshot_and_panel_parity(
    workspace_server: tuple[int, str, str],
) -> None:
    port, token, _ = workspace_server
    session_id = _create_session(port, token)
    code, _, body = _request(
        port,
        "GET",
        f"/api/workspace/sessions/{session_id}/snapshot",
        token=token,
    )
    assert code == 200
    snapshot = _json(body)
    panels = cast(list[dict[str, object]], snapshot["panels"])
    assert tuple(panel["key"] for panel in panels) == EXPECTED_PANEL_KEYS
    assert snapshot["session_id"] == session_id
    assert snapshot["cursor"] == 0


def test_chat_command_streams_ordered_events_and_deduplicates(
    workspace_server: tuple[int, str, str],
) -> None:
    port, token, _ = workspace_server
    session_id = _create_session(port, token)
    command = _command(
        "browser-1:command-1",
        expected_cursor=0,
        command_type="chat.send",
        payload={"text": "hello"},
    )
    code, _, body = _request(
        port,
        "POST",
        f"/api/workspace/sessions/{session_id}/commands",
        token=token,
        body=command,
    )
    assert code == 202
    assert _json(body)["state"] == "accepted"

    code, headers, body = _request(
        port,
        "GET",
        (
            f"/api/workspace/sessions/{session_id}/events"
            "?after=0&once=1&until=command.completed"
        ),
        token=token,
    )
    assert code == 200
    assert headers["Content-Type"].startswith("text/event-stream")
    events = _sse_events(body)
    assert [event["cursor"] for event in events] == [1, 2, 3]
    assert [event["type"] for event in events] == [
        "command.accepted",
        "command.started",
        "command.completed",
    ]
    assert {event["actor_id"] for event in events} == {"web:browser-1"}

    code, _, body = _request(
        port,
        "POST",
        f"/api/workspace/sessions/{session_id}/commands",
        token=token,
        body=command,
    )
    assert code == 200
    assert _json(body)["duplicate"] is True


def test_web_approval_payload_executes_through_runtime_authority(
    workspace_server: tuple[int, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decided: list[tuple[str, str]] = []

    def decide(
        approval_id: str,
        *,
        decision: str,
        reason: str = "",
        on_event: object = None,
    ) -> dict[str, object]:
        assert on_event is not None
        assert reason == ""
        decided.append((approval_id, decision))
        return {
            "outcome": "approved",
            "approval_id": approval_id,
        }

    monkeypatch.setattr(web_server, "_workspace_handlers", None, raising=False)
    monkeypatch.setattr(web_server, "_workspace_adapters", {}, raising=False)
    monkeypatch.setattr(approval_authority, "decide", decide)
    port, token, _ = workspace_server
    session_id = _create_session(port, token)
    approval_id = "abc123def456"
    command = _command(
        "browser-1:approval-1",
        expected_cursor=0,
        command_type="approval.answer",
        payload=_web_approval_payload(approval_id, "approve"),
    )

    code, _, body = _request(
        port,
        "POST",
        f"/api/workspace/sessions/{session_id}/commands",
        token=token,
        body=command,
    )
    assert code == 202
    assert _json(body)["state"] == "accepted"

    code, _, body = _request(
        port,
        "GET",
        (
            f"/api/workspace/sessions/{session_id}/events"
            "?after=0&once=1&until=command.completed"
        ),
        token=token,
    )
    assert code == 200
    events = _sse_events(body)
    assert [event["type"] for event in events] == [
        "command.accepted",
        "command.started",
        "approval.answered",
        "command.completed",
    ]
    assert decided == [(approval_id, "approve")]


def test_interrupt_resume_and_actor_spoof_rejection(
    workspace_server: tuple[int, str, str],
) -> None:
    port, token, _ = workspace_server
    session_id = _create_session(port, token)
    forged = _command(
        "browser-1:command-1",
        expected_cursor=0,
        command_type="chat.interrupt",
        payload={},
    )
    forged["actor_id"] = "forged:admin"
    assert _request(
        port,
        "POST",
        f"/api/workspace/sessions/{session_id}/commands",
        token=token,
        body=forged,
    )[0] == 400

    interrupt = _command(
        "browser-1:command-2",
        expected_cursor=0,
        command_type="chat.interrupt",
        payload={},
    )
    assert _request(
        port,
        "POST",
        f"/api/workspace/sessions/{session_id}/commands",
        token=token,
        body=interrupt,
    )[0] == 202
    code, _, body = _request(
        port,
        "GET",
        (
            f"/api/workspace/sessions/{session_id}/events"
            "?after=0&once=1&until=command.completed"
        ),
        token=token,
    )
    assert code == 200
    events = _sse_events(body)
    cursor = cast(int, events[-1]["cursor"])

    resume = _command(
        "browser-1:command-3",
        expected_cursor=cursor,
        command_type="chat.resume",
        payload={},
    )
    assert _request(
        port,
        "POST",
        f"/api/workspace/sessions/{session_id}/commands",
        token=token,
        body=resume,
    )[0] == 202


def test_web_interrupt_signals_runtime_before_serial_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signaled: list[str] = []

    class Adapter:
        def interrupt_now(self) -> None:
            signaled.append("interrupt")

    adapters = cast(
        dict[str, object],
        vars(web_server)["_workspace_adapters"],
    )
    monkeypatch.setitem(adapters, "interrupt-session", Adapter())

    signal = getattr(web_server, "signal_workspace_interrupt", None)
    assert callable(signal), "web interrupt pre-signal is missing"
    assert signal("interrupt-session") is True
    assert signaled == ["interrupt"]


def _bootstrap_cookie(port: int, nonce: str) -> str:
    connection = http.client.HTTPConnection(
        "127.0.0.1", port, timeout=local_http_timeout()
    )
    connection.request(
        "GET",
        f"/_bootstrap/{nonce}",
        headers={"Host": f"127.0.0.1:{port}"},
    )
    response = connection.getresponse()
    _ = response.read()
    headers = dict(response.getheaders())
    connection.close()
    assert response.status == 303
    return headers["Set-Cookie"].split(";", 1)[0]


def test_bootstrap_capability_is_consumed_once(
    workspace_server: tuple[int, str, str],
) -> None:
    port, _, nonce = workspace_server
    _ = _bootstrap_cookie(port, nonce)

    code, headers, _ = _request(
        port,
        "GET",
        f"/_bootstrap/{nonce}",
    )
    assert code == 403
    assert "Set-Cookie" not in headers


def test_cookie_authenticated_post_requires_same_origin_json(
    workspace_server: tuple[int, str, str],
) -> None:
    port, _, nonce = workspace_server
    cookie = _bootstrap_cookie(port, nonce)
    payload = json.dumps({"session_id": "csrf"}).encode("utf-8")

    for origin, content_type, expected in (
        ("http://127.0.0.1:9999", "text/plain", 403),
        (f"http://127.0.0.1:{port}", "text/plain", 415),
    ):
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            port,
            timeout=local_http_timeout(),
        )
        connection.request(
            "POST",
            "/api/workspace/sessions",
            body=payload,
            headers={
                "Host": f"127.0.0.1:{port}",
                "Cookie": cookie,
                "Origin": origin,
                "Sec-Fetch-Site": (
                    "same-origin"
                    if origin.endswith(str(port))
                    else "same-site"
                ),
                "Content-Type": content_type,
                "Content-Length": str(len(payload)),
            },
        )
        response = connection.getresponse()
        _ = response.read()
        connection.close()
        assert response.status == expected


def test_workspace_stream_limit_rejects_excess_subscriber(
    workspace_server: tuple[int, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, token, _ = workspace_server
    session_id = _create_session(port, token)
    monkeypatch.setattr(
        web_server,
        "_workspace_stream_slots",
        threading.Semaphore(0),
    )

    code, _, body = _request(
        port,
        "GET",
        f"/api/workspace/sessions/{session_id}/events?after=0",
        token=token,
    )
    assert code == 503
    assert _json(body)["error"] == "workspace stream capacity reached"


def test_attached_workspace_qa_uses_listener_nonce(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
    session = tmp_path / "web_session.json"
    session.write_text(
        json.dumps({
            "port": 43210,
            "token": "process-capability",
            "bootstrap_nonce": "listener-nonce",
        }),
        encoding="utf-8",
    )
    observed_urls: list[str] = []
    monkeypatch.delenv("BIRKIN_HTTP_TOKEN", raising=False)
    monkeypatch.setattr(
        workspace_web_e2e.config,
        "birkin_home",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        workspace_web_e2e,
        "_run_driver",
        lambda url, _evidence: observed_urls.append(url),
    )
    monkeypatch.setattr(
        workspace_web_e2e,
        "_png_dimensions",
        lambda path: workspace_web_e2e.SCREENSHOTS[path.name],
    )
    monkeypatch.setattr(
        workspace_web_e2e.sys,
        "argv",
        [
            "workspace_web_e2e.py",
            "--base-url",
            "http://127.0.0.1:43210",
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ],
    )

    assert workspace_web_e2e.main() == 0
    assert observed_urls == [
        "http://127.0.0.1:43210/_bootstrap/listener-nonce"
    ]
