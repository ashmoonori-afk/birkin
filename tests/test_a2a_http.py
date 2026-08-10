"""The A2A endpoints as another agent actually reaches them: over HTTP.

The module answering JSON-RPC correctly proves nothing about whether a peer
can reach it. These drive a real HTTPServer on a real port with real requests,
because "off" has to mean 404 on the wire, not merely a False in a dict.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from birkin.web import server as web


@pytest.fixture()
def live(monkeypatch, tmp_path):
    """A real dashboard server on an ephemeral port."""
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    started: list = []

    def _start(cfg):
        monkeypatch.setattr(web.config, "load_config", lambda: cfg)
        httpd = HTTPServer(("127.0.0.1", 0), web.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        started.append((httpd, thread))
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield _start
    for httpd, thread in started:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post(url: str, payload: dict, token: str | None) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 **({"X-Birkin-Token": token} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class TestWhileOffItIsInvisible:
    def test_the_card_is_a_plain_404(self, live) -> None:
        base = live({"a2a_enabled": False})
        code, body = _get(f"{base}/.well-known/agent-card.json")
        assert code == 404
        assert b"a2a" not in body.lower()

    def test_the_rpc_endpoint_is_a_plain_404(self, live) -> None:
        base = live({"a2a_enabled": False})
        code, _ = _post(f"{base}/a2a", {"jsonrpc": "2.0", "id": 1,
                                        "method": "tasks/get",
                                        "params": {"id": "x"}}, web._TOKEN)
        assert code == 404

    def test_the_default_config_leaves_it_off(self, live) -> None:
        from birkin import config
        base = live(dict(config.DEFAULT_CONFIG))
        assert _get(f"{base}/.well-known/agent-card.json")[0] == 404


class TestWhileOnItServesTheProtocol:
    def test_the_card_is_served_as_json(self, live) -> None:
        base = live({"a2a_enabled": True})
        code, body = _get(f"{base}/.well-known/agent-card.json")
        assert code == 200
        card = json.loads(body)
        assert card["protocolVersion"].startswith("1.")
        assert card["url"].endswith("/a2a")

    def test_message_send_returns_a_completed_task(self, live, monkeypatch) -> None:
        monkeypatch.setattr(web, "_a2a_run", lambda text: f"echo:{text}",
                            raising=False)
        base = live({"a2a_enabled": True})
        code, body = _post(f"{base}/a2a", {
            "jsonrpc": "2.0", "id": 7, "method": "message/send",
            "params": {"message": {"role": "user", "parts": [
                {"kind": "text", "text": "ping"}]}}}, web._TOKEN)
        assert code == 200
        reply = json.loads(body)
        assert reply["id"] == 7
        # Deliberately NOT "completed or failed": that looseness hid a
        # _a2a_run that called a function which did not exist, turning every
        # peer task into a failed one carrying an ImportError.
        assert reply["result"]["status"]["state"] == "completed"
        assert "echo:ping" in json.dumps(reply, ensure_ascii=False)

    def test_the_rpc_still_needs_the_dashboard_token(self, live) -> None:
        """An RPC that submits work is at least as consequential as approving."""
        base = live({"a2a_enabled": True})
        code, _ = _post(f"{base}/a2a", {"jsonrpc": "2.0", "id": 1,
                                        "method": "tasks/get",
                                        "params": {"id": "x"}}, None)
        assert code == 403

    def test_a_malformed_body_is_a_json_rpc_error_not_a_crash(self, live) -> None:
        base = live({"a2a_enabled": True})
        request = urllib.request.Request(
            f"{base}/a2a", data=b"{not json",
            headers={"Content-Type": "application/json",
                     "X-Birkin-Token": web._TOKEN})
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                code, _ = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            code, _ = exc.code, exc.read()
        assert code == 400

    def test_the_dashboard_still_works_with_a2a_on(self, live) -> None:
        """Adjacent surface: mounting A2A must not shadow the existing routes."""
        base = live({"a2a_enabled": True})
        assert _get(f"{base}/api/status")[0] == 200


def test_the_default_runner_resolves_the_real_session_api() -> None:
    """_a2a_run must call something that exists.

    The monkeypatched tests above never execute it, and a task that fails
    because of an ImportError looks exactly like a task that failed because
    the model was down.
    """
    import inspect

    from birkin import runtime

    source = inspect.getsource(web._a2a_run)
    called = [name for name in ("build_session", "one_shot")
              if name in source]
    assert called, "the runner calls nothing recognisable"
    for name in called:
        assert hasattr(runtime, name), f"runtime has no {name}"
