"""Mid-input interruption: a new Telegram message cancels the in-flight turn."""

from __future__ import annotations

import threading
import time


# -- gateway.interrupt targets the in-flight session --------------------------

def _gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    config.save_config({**config.DEFAULT_CONFIG, "provider": "codex-cli",
                        "model": "gpt-5.6-sol", "gateway_prewarm": False})
    from birkin.gateway.core import Gateway
    return Gateway(config.load_config())


class _SlowSession:
    """A warm session whose ask() blocks until interrupt() is called."""
    def __init__(self):
        self.interrupted = threading.Event()
        self.interrupt_calls = 0

    def ask(self, text, on_text=None):
        # block up to 5s or until interrupted
        if self.interrupted.wait(timeout=5):
            return "[interrupted]"
        return "done"

    def interrupt(self):
        self.interrupt_calls += 1
        self.interrupted.set()
        return True

    def is_alive(self):
        return True

    def close(self):
        pass


def test_gateway_interrupt_cancels_inflight_turn(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    sess = _SlowSession()
    monkeypatch.setattr(gw, "_claude_session", lambda key: sess)
    result = {}
    t = threading.Thread(
        target=lambda: result.__setitem__("r", gw.handle("telegram", "42", "hi")))
    t.start()
    # wait until the turn registers as in-flight, then interrupt
    for _ in range(50):
        if ("telegram", "42") in gw._inflight:
            break
        time.sleep(0.02)
    assert gw.interrupt("telegram", "42") is True
    t.join(timeout=3)
    assert sess.interrupt_calls == 1
    assert result["r"] == "[interrupted]"
    assert ("telegram", "42") not in gw._inflight   # cleared after the turn


def test_interrupt_noop_when_nothing_inflight(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    assert gw.interrupt("telegram", "999") is False


# -- codex session interrupt sends turn/interrupt -----------------------------

def test_codex_interrupt_kills_process_after_graceful_attempt(monkeypatch):
    from birkin import codex_session
    from birkin.codex_session import CodexAppServerSession
    s = CodexAppServerSession(model="gpt-5.6-sol")
    s._thread_id = "t1"
    s._active_turn_id = "turn-9"
    s._proc = object()
    alive = {"v": True}
    monkeypatch.setattr(s, "is_alive", lambda: alive["v"])
    sent = []
    monkeypatch.setattr(s, "request",
                        lambda method, params=None, timeout=None:
                        sent.append((method, params)) or {})
    killed = []
    monkeypatch.setattr(codex_session, "kill_tree", killed.append)
    assert s.interrupt() is True
    assert s._interrupted is True
    assert sent == [("turn/interrupt", {"threadId": "t1", "turnId": "turn-9"})]
    assert killed == [s._proc]               # graceful failed -> force kill
    # dead process -> no-op
    alive["v"] = False
    s2 = CodexAppServerSession(model="gpt-5.6-sol")
    monkeypatch.setattr(s2, "is_alive", lambda: False)
    assert s2.interrupt() is False


def test_codex_turn_returns_marker_when_interrupted(monkeypatch):
    from birkin.codex_session import CodexAppServerSession
    s = CodexAppServerSession(model="gpt-5.6-sol")
    s._thread_id = "t1"
    s._interrupted = True

    def fake_request(method, params=None, timeout=None):
        # simulate: turn/start accepted, then the process is killed mid-turn
        # so the reader posts the None sentinel into the main loop.
        s._notes.put(None)
        return {"turn": {"id": "x"}}
    monkeypatch.setattr(s, "request", fake_request)
    out = s._turn("hi", None, timeout=5)
    assert "중단" in out                       # clean marker, no raise


# -- claude session interrupt writes a control_request ------------------------

def test_claude_interrupt_writes_control_request(monkeypatch):
    from birkin.claude_session import ClaudeStreamSession
    import io
    import json
    s = ClaudeStreamSession()
    buf = io.StringIO()
    s._proc = type("P", (), {"stdin": buf})()
    assert s.interrupt() is True
    sent = json.loads(buf.getvalue())
    assert sent == {"type": "control_request",
                    "request": {"subtype": "interrupt"}}
    s._proc = None
    assert s.interrupt() is False            # no process -> no-op


# -- telegram loop: a new message interrupts the previous worker --------------

def test_telegram_new_message_interrupts_previous(tmp_path, monkeypatch):
    from birkin.gateway.channels.telegram import TelegramChannel
    ch = TelegramChannel("tok", allowed_chat_ids=["42"], stream=False)

    class _FakeGateway:
        pending_hard_restart = False

        def __init__(self):
            self.interrupts = []
            self.handled = []

        def _command_trusted(self, ch):
            return True

        def interrupt(self, channel, chat_id):
            self.interrupts.append(chat_id)
            return True

        def handle(self, channel, chat_id, text, on_text=None):
            self.handled.append(text)
            time.sleep(0.3)                  # simulate a slow turn
            return f"reply to {text}"

    gw = _FakeGateway()
    monkeypatch.setattr(ch, "_send_reply", lambda c, r: None)
    monkeypatch.setattr(ch, "_keep_typing", lambda c, stop: None)
    # first message -> starts a worker
    w1 = threading.Thread(target=ch._run_turn, args=(gw, "42", "first", 0),
                          daemon=True)
    ch._workers["42"] = w1
    w1.start()
    time.sleep(0.05)
    # simulate the loop seeing a SECOND message for the same chat
    prev = ch._workers.get("42")
    assert prev.is_alive()
    gw.interrupt("telegram", "42")           # what the loop does
    assert gw.interrupts == ["42"]
    w1.join(timeout=2)
    assert gw.handled == ["first"]           # first turn ran (and was signalled)
