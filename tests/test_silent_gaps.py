"""P1-3: no silent gaps — friendly gateway errors + visible retry/backoff."""

from __future__ import annotations

import io
import urllib.error

from birkin.llm import LLMClient


def _client():
    return LLMClient(provider="anthropic", model="m", api_key="k",
                     base_url="https://x")


def test_backoff_is_surfaced_via_status_sink(monkeypatch):
    c = _client()
    seen: list[str] = []
    c._status = seen.append
    monkeypatch.setattr("birkin.llm.time.sleep", lambda s: None)
    attempts = {"n": 0}

    def fake_urlopen(req, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise urllib.error.HTTPError("u", 429, "Too Many", {},
                                         io.BytesIO(b'{"e":1}'))
        return io.BytesIO(b'{"ok":1}')
    monkeypatch.setattr("birkin.llm.urllib.request.urlopen", fake_urlopen)
    c._post("https://x", {}, {}, stream=False)
    assert seen and "rate-limited" in seen[0] and "2/4" in seen[0]


def test_backoff_prints_when_no_status_sink(monkeypatch, capsys):
    c = _client()                                   # _status is None
    monkeypatch.setattr("birkin.llm.time.sleep", lambda s: None)
    attempts = {"n": 0}

    def fake_urlopen(req, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise urllib.error.URLError("conn reset")
        return io.BytesIO(b"{}")
    monkeypatch.setattr("birkin.llm.urllib.request.urlopen", fake_urlopen)
    c._post("https://x", {}, {}, stream=False)
    assert "network error" in capsys.readouterr().out


def test_gateway_error_is_friendly_not_raw(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "claude-cli",
                        "gateway_prewarm": False, "gateway_persistent": False})
    from birkin.gateway.core import Gateway
    gw = Gateway(config.load_config())

    class _Boom:
        def __init__(self):
            self.agent = type("A", (), {"messages": []})()

        def ask(self, text):
            raise RuntimeError("C:/secret/path leaked in traceback")
    gw.session = _Boom()
    out = gw.handle("telegram", "c1", "hello")
    assert "secret" not in out and "path" not in out   # no internal leak
    assert "⚠️" in out                                 # friendly line
