"""P1-1a: opt-in warm CLI session for the REPL (reuse one process)."""

from __future__ import annotations


def _session(tmp_path, monkeypatch, **over):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    from birkin.runtime import build_session
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "model": "haiku", **over}
    config.save_config(cfg)
    return build_session(cfg)


class _FakeWarm:
    def __init__(self):
        self.asks: list[str] = []
        self.closed = False

    def ask(self, text, on_text=None):
        self.asks.append(text)
        if on_text:
            on_text("warm reply")
        return "warm reply"

    def close(self):
        self.closed = True


def test_warm_off_by_default_uses_agent_run(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch)                 # flag not set
    assert s._use_warm() is False
    called = {"agent": 0}
    monkeypatch.setattr(s.agent, "run",
                        lambda *a, **k: called.__setitem__("agent", 1) or "x")
    s.ask("hi")
    assert called["agent"] == 1                         # legacy path
    assert s._warm is None                              # no warm process built


def test_warm_on_routes_to_warm_session_and_reuses_it(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, repl_warm_session=True)
    assert s._use_warm() is True
    fake = _FakeWarm()
    monkeypatch.setattr(s, "_build_warm", lambda: fake)
    monkeypatch.setattr(s.agent, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("agent.run must not run on warm path")))
    pieces: list[str] = []
    assert s.ask("first", on_text=pieces.append) == "warm reply"
    assert s.ask("second") == "warm reply"
    assert fake.asks == ["first", "second"]             # SAME process reused
    assert pieces == ["warm reply"]                     # on_text threaded
    s.close()
    assert fake.closed is True and s._warm is None


def test_warm_disabled_for_non_cli_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = _session(tmp_path, monkeypatch, provider="anthropic",
                 repl_warm_session=True)
    assert s._use_warm() is False                       # API path never warms


def test_build_warm_picks_codex_for_codex_provider(tmp_path, monkeypatch):
    from birkin.codex_session import CodexAppServerSession
    s = _session(tmp_path, monkeypatch, provider="codex-cli",
                 model="gpt-5.5", repl_warm_session=True)
    w = s._build_warm()                                 # constructor: no spawn
    assert isinstance(w, CodexAppServerSession)
    assert w.preamble                                   # persona/memory rides it
    w.close()
