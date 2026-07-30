"""Mid-input interruption: a new Telegram message cancels the in-flight turn."""

from __future__ import annotations

import threading

import pytest


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
        self.started = threading.Event()
        self.interrupted = threading.Event()
        self.interrupt_calls = 0

    def ask(self, text, on_text=None):
        # block up to 5s or until interrupted
        self.started.set()
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
    gw._claude_sessions.put(("telegram", "42"), sess)
    result = {}
    t = threading.Thread(
        target=lambda: result.__setitem__("r", gw.handle("telegram", "42", "hi")))
    t.start()
    assert sess.started.wait(timeout=2)
    assert gw.interrupt("telegram", "42") is True
    t.join(timeout=3)
    assert sess.interrupt_calls == 1
    assert result["r"] == "[interrupted]"
    assert ("telegram", "42") not in gw._inflight   # cleared after the turn


def test_interrupt_noop_when_nothing_inflight(tmp_path, monkeypatch):
    gw = _gateway(tmp_path, monkeypatch)
    assert gw.interrupt("telegram", "999") is False


class _LeaseSession:
    def __init__(self, *, error=None):
        self.error = error

    def ask(self, text, on_text=None):
        if self.error is not None:
            raise self.error
        return "done"

    def interrupt(self):
        return True

    def is_alive(self):
        return True

    def close(self):
        pass


class _BookkeepingError(RuntimeError):
    pass


class _LeasePoolSpy:
    def __init__(self, gateway, session, *, borrow_error=None):
        self.gateway = gateway
        self.session = session
        self.borrow_error = borrow_error
        self.borrow_calls = []
        self.release_calls = []
        self.inflight_at_release = []
        self.outstanding = 0

    def get(self, key):
        raise AssertionError("Gateway.handle must borrow, never get")

    def borrow(self, key):
        self.borrow_calls.append(key)
        if self.borrow_error is not None:
            raise self.borrow_error
        self.outstanding += 1
        return self.session

    def release(self, key, session):
        assert self.outstanding == 1
        assert session is self.session
        assert not self.release_calls
        self.inflight_at_release.append(key in self.gateway._inflight)
        self.release_calls.append((key, session))
        self.outstanding -= 1


def _lease_gateway(tmp_path, monkeypatch, session=None, *, borrow_error=None):
    from birkin import store, transcripts

    gw = _gateway(tmp_path, monkeypatch)
    session = session or _LeaseSession()
    pool = _LeasePoolSpy(gw, session, borrow_error=borrow_error)
    gw._claude_sessions = pool
    monkeypatch.setattr(
        gw.session, "_prepare_cli_turn", lambda text, **_kwargs: text)
    monkeypatch.setattr(gw.session, "_record_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(store, "append_activity", lambda _text: None)
    monkeypatch.setattr(transcripts, "append_turn", lambda *_args, **_kwargs: None)
    return gw, pool, session


def _assert_released(pool, session, *, inflight_at_release=False):
    key = ("http", "42")
    assert pool.borrow_calls == [key]
    assert pool.release_calls == [(key, session)]
    assert pool.inflight_at_release == [inflight_at_release]
    assert pool.outstanding == 0


def test_gateway_releases_session_after_turn_error(tmp_path, monkeypatch):
    from birkin.gateway.core import TURN_ERROR_REPLY

    gw, pool, session = _lease_gateway(
        tmp_path, monkeypatch, _LeaseSession(error=RuntimeError("ask failed")))

    assert gw.handle("http", "42", "hello") == TURN_ERROR_REPLY
    _assert_released(pool, session)


def test_gateway_releases_session_after_pre_ask_error(tmp_path, monkeypatch):
    gw, pool, session = _lease_gateway(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gw, "_command_trusted",
        lambda _channel: (_ for _ in ()).throw(RuntimeError("trust failed")))

    with pytest.raises(RuntimeError, match="trust failed"):
        gw.handle("http", "42", "hello")
    _assert_released(pool, session)


def test_gateway_releases_session_when_inflight_registration_fails(
        tmp_path, monkeypatch):
    from birkin.gateway.core import TURN_ERROR_REPLY

    class _FailFirstLock:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            self.calls += 1
            if self.calls == 1:
                raise _BookkeepingError("registration failed")
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    gw, pool, session = _lease_gateway(tmp_path, monkeypatch)
    lock = _FailFirstLock()
    gw._inflight_lock = lock

    assert gw.handle("http", "42", "hello") == TURN_ERROR_REPLY
    assert lock.calls == 2
    assert not gw._inflight
    _assert_released(pool, session)


def test_gateway_releases_session_after_success(tmp_path, monkeypatch):
    gw, pool, session = _lease_gateway(tmp_path, monkeypatch)

    assert gw.handle("http", "42", "hello") == "done"
    _assert_released(pool, session)


def test_gateway_releases_session_after_last_operation_error(
        tmp_path, monkeypatch):
    from birkin import transcripts

    gw, pool, session = _lease_gateway(tmp_path, monkeypatch)
    monkeypatch.setattr(
        transcripts, "append_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("autosave failed")))

    with pytest.raises(RuntimeError, match="autosave failed"):
        gw.handle("http", "42", "hello")
    _assert_released(pool, session)


def test_gateway_release_survives_inflight_cleanup_error(tmp_path, monkeypatch):
    class _FailCleanupLock:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            self.calls += 1
            if self.calls == 2:
                raise _BookkeepingError("cleanup failed")
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    gw, pool, session = _lease_gateway(tmp_path, monkeypatch)
    lock = _FailCleanupLock()
    gw._inflight_lock = lock

    with pytest.raises(_BookkeepingError, match="cleanup failed"):
        gw.handle("http", "42", "hello")

    assert lock.calls == 2
    _assert_released(pool, session, inflight_at_release=True)


def test_gateway_pool_full_returns_friendly_error_without_inflight(
        tmp_path, monkeypatch):
    from birkin import pools
    from birkin.gateway.core import TURN_ERROR_REPLY

    gw, pool, _session = _lease_gateway(
        tmp_path, monkeypatch, borrow_error=pools.SessionPoolFullError(1))

    assert gw.handle("http", "42", "hello") == TURN_ERROR_REPLY
    assert pool.borrow_calls == [("http", "42")]
    assert pool.release_calls == []
    assert pool.outstanding == 0
    assert not gw._inflight


def test_old_turn_cannot_unregister_newer_inflight_turn(tmp_path, monkeypatch):
    from birkin import pools, store, transcripts

    old_asking = threading.Event()
    new_asking = threading.Event()
    finish_old = threading.Event()
    finish_new = threading.Event()

    class _RacingSession(_LeaseSession):
        def __init__(self):
            super().__init__()
            self.interrupt_calls = 0

        def ask(self, text, on_text=None):
            if text == "old":
                old_asking.set()
                assert finish_old.wait(timeout=2)
                return "old-done"
            new_asking.set()
            assert finish_new.wait(timeout=2)
            return "new-done"

        def interrupt(self):
            self.interrupt_calls += 1
            return True

    gw = _gateway(tmp_path, monkeypatch)
    session = _RacingSession()
    gw._claude_sessions = pools.SessionPool(lambda _key: session)
    monkeypatch.setattr(
        gw.session, "_prepare_cli_turn", lambda text, **_kwargs: text)
    monkeypatch.setattr(gw.session, "_record_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(store, "append_activity", lambda _text: None)
    monkeypatch.setattr(transcripts, "append_turn", lambda *_args, **_kwargs: None)
    results = {}
    old = threading.Thread(
        target=lambda: results.__setitem__("old", gw.handle("http", "42", "old")))
    new = threading.Thread(
        target=lambda: results.__setitem__("new", gw.handle("http", "42", "new")))

    old.start()
    assert old_asking.wait(timeout=2)
    new.start()
    assert new_asking.wait(timeout=2)
    try:
        finish_old.set()
        old.join(timeout=2)
        assert not old.is_alive()
        interrupted = gw.interrupt("http", "42")
    finally:
        finish_old.set()
        finish_new.set()
        old.join(timeout=2)
        new.join(timeout=2)

    assert interrupted is True
    assert session.interrupt_calls == 1
    assert not old.is_alive() and not new.is_alive()
    assert results == {"old": "old-done", "new": "new-done"}
    assert ("http", "42") not in gw._inflight


def test_failed_new_turn_leaves_active_predecessor_interruptible(
        tmp_path, monkeypatch):
    from birkin import store, transcripts
    from birkin.gateway.core import TURN_ERROR_REPLY

    old_asking = threading.Event()
    new_preparing = threading.Event()
    allow_new_failure = threading.Event()
    release_old = threading.Event()

    class _BlockingSession(_LeaseSession):
        def __init__(self, asking):
            super().__init__()
            self.asking = asking
            self.interrupt_calls = 0

        def ask(self, text, on_text=None):
            self.asking.set()
            assert release_old.wait(timeout=2)
            return "old-done"

        def interrupt(self):
            self.interrupt_calls += 1
            return True

    class _TwoSessionPool:
        def __init__(self, sessions):
            self.sessions = list(sessions)
            self.borrow_calls = []
            self.release_calls = []

        def borrow(self, key):
            self.borrow_calls.append(key)
            return self.sessions.pop(0)

        def release(self, key, session):
            self.release_calls.append((key, session))

    old_session = _BlockingSession(old_asking)
    new_asked = threading.Event()
    new_session = _BlockingSession(new_asked)
    gw = _gateway(tmp_path, monkeypatch)
    pool = _TwoSessionPool([old_session, new_session])
    gw._claude_sessions = pool

    def prepare(text, **_kwargs):
        if text == "new":
            new_preparing.set()
            assert allow_new_failure.wait(timeout=2)
            raise RuntimeError("new failed before ask")
        return text

    monkeypatch.setattr(gw.session, "_prepare_cli_turn", prepare)
    monkeypatch.setattr(gw.session, "_record_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(store, "append_activity", lambda _text: None)
    monkeypatch.setattr(transcripts, "append_turn", lambda *_args, **_kwargs: None)
    key = ("http", "42")
    results = {}
    old = threading.Thread(
        target=lambda: results.__setitem__("old", gw.handle(*key, "old")))
    new = threading.Thread(
        target=lambda: results.__setitem__("new", gw.handle(*key, "new")))

    old.start()
    assert old_asking.wait(timeout=2)
    assert old.is_alive()
    new.start()
    assert new_preparing.wait(timeout=2)
    assert new.is_alive()
    try:
        overlap_interrupted = gw.interrupt(*key)
        assert old.is_alive()
        allow_new_failure.set()
        new.join(timeout=2)
        assert not new.is_alive()
        assert old.is_alive()
        assert not new_asked.is_set()
        assert pool.release_calls == [(key, new_session)]
        predecessor_interrupted = gw.interrupt(*key)
    finally:
        allow_new_failure.set()
        release_old.set()
        old.join(timeout=2)
        new.join(timeout=2)

    assert not old.is_alive() and not new.is_alive()
    assert predecessor_interrupted is True
    assert overlap_interrupted is True
    assert old_session.interrupt_calls == 2
    assert new_session.interrupt_calls == 1
    assert pool.borrow_calls == [key, key]
    assert pool.release_calls == [(key, new_session), (key, old_session)]
    assert results == {"new": TURN_ERROR_REPLY, "old": "old-done"}
    assert key not in gw._inflight


def test_interrupt_calls_session_after_releasing_inflight_lock(
        tmp_path, monkeypatch):
    class _OwnershipLock:
        def __init__(self):
            self.lock = threading.Lock()
            self.owner = None
            self.acquisitions = 0

        def __enter__(self):
            self.lock.acquire()
            self.owner = threading.get_ident()
            self.acquisitions += 1
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.owner = None
            self.lock.release()

        def owned_by_current_thread(self):
            return self.owner == threading.get_ident()

    gw = _gateway(tmp_path, monkeypatch)
    lock = _OwnershipLock()
    calls = []

    class _OwnershipSession:
        def __init__(self, name, *, error=False):
            self.name = name
            self.error = error

        def interrupt(self):
            assert not lock.owned_by_current_thread()
            calls.append(self.name)
            if self.error:
                raise RuntimeError("interrupt failed")
            return True

    gw._inflight_lock = lock
    old = _OwnershipSession("old")
    gw._inflight[("http", "42")] = [
        (object(), old, threading.Event()),
        (object(), old, threading.Event()),
        (object(), _OwnershipSession("new", error=True), threading.Event()),
    ]

    assert gw.interrupt("http", "42") is True
    assert lock.acquisitions == 1
    assert calls == ["new", "old"]


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
            self.started = threading.Event()
            self.release = threading.Event()

        def _command_trusted(self, ch):
            return True

        def interrupt(self, channel, chat_id):
            self.interrupts.append(chat_id)
            self.release.set()
            return True

        def handle(self, channel, chat_id, text, on_text=None):
            self.handled.append(text)
            self.started.set()
            assert self.release.wait(timeout=2)
            return f"reply to {text}"

    gw = _FakeGateway()
    monkeypatch.setattr(ch, "_send_reply", lambda c, r: None)
    monkeypatch.setattr(ch, "_keep_typing", lambda c, stop: None)
    # first message -> starts a worker
    w1 = threading.Thread(target=ch._run_turn, args=(gw, "42", "first", 0),
                          daemon=True)
    ch._workers["42"] = w1
    w1.start()
    assert gw.started.wait(timeout=2)
    # simulate the loop seeing a SECOND message for the same chat
    prev = ch._workers.get("42")
    assert prev.is_alive()
    gw.interrupt("telegram", "42")           # what the loop does
    assert gw.interrupts == ["42"]
    w1.join(timeout=2)
    assert gw.handled == ["first"]           # first turn ran (and was signalled)


def test_telegram_messages_interrupt_gateway_behind_dead_worker(monkeypatch):
    from birkin.gateway import workflow
    from birkin.gateway.channels import telegram

    class _StopPolling(BaseException):
        pass

    class _DeadWorker:
        def __init__(self):
            self.join_calls = 0

        def is_alive(self):
            return False

        def join(self, timeout=None):
            self.join_calls += 1

    class _InlineThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

        def is_alive(self):
            return False

    class _FakeGateway:
        def __init__(self):
            self.interrupts = []

        def take_restart_greeting(self, channel):
            return None

        def _command_trusted(self, channel):
            return True

        def interrupt(self, channel, chat_id):
            self.interrupts.append((channel, chat_id))
            return True

    ch = telegram.TelegramChannel(
        "tok", allowed_chat_ids=["42"], stream=False)
    gateway = _FakeGateway()
    dead = _DeadWorker()
    ch._workers["42"] = dead
    pending = []
    turns = []
    responses = [
        {},
        {},
        {"result": [
            {"update_id": 1, "message": {
                "chat": {"id": 99}, "text": "unauthorized"}},
            {"update_id": 2, "message": {
                "chat": {"id": 42}, "text": "/pending"}},
            {"update_id": 3, "message": {
                "chat": {"id": 42}, "text": "hello"}},
        ]},
    ]

    def call(_method, _params, timeout=60):
        if responses:
            return responses.pop(0)
        raise _StopPolling

    monkeypatch.setattr(workflow, "restore_stranded_claims", lambda: 0)
    monkeypatch.setattr(ch, "_call", call)
    monkeypatch.setattr(
        ch, "_send_pending_buttons",
        lambda _gateway, chat_id: pending.append(chat_id))
    monkeypatch.setattr(
        ch, "_run_turn",
        lambda _gateway, chat_id, text, _offset:
        turns.append((chat_id, text)))
    monkeypatch.setattr(telegram.threading, "Thread", _InlineThread)

    with pytest.raises(_StopPolling):
        ch.start(gateway)

    assert gateway.interrupts == [
        ("telegram", "42"), ("telegram", "42")]
    assert dead.join_calls == 0
    assert pending == ["42"]
    assert turns == [("42", "hello")]
