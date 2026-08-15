"""Unit tests for the persistent Claude stream-json session.

No real ``claude`` process is launched: ``subprocess.Popen`` is replaced by a
fake that turns each stream-json user message written to stdin into a canned
sequence of stream-json events on stdout. This exercises the framing, result
parsing, conversation continuity (only the new turn is sent), error handling,
on_text callback, and dead-process restart — deterministically and offline.
"""

from __future__ import annotations

import json
import queue

import pytest

from birkin import claude_session
from birkin.claude_session import ClaudeStreamSession


class _FakeStdin:
    """Captures user messages and enqueues canned response events on stdout."""

    def __init__(
        self,
        out_q: queue.Queue[object],
        sent: list[object],
        behavior,
    ):
        self._out = out_q
        self._sent = sent
        self._behavior = behavior
        self.closed = False

    def write(self, data: str) -> None:
        line = data.strip()
        if not line:
            return
        msg = json.loads(line)
        text = msg["message"]["content"]
        self._sent.append(text)
        for event in self._behavior(text):
            self._out.put(json.dumps(event) + "\n")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _BlockingLines:
    """Iterable yielding queued lines; blocks until more arrive (like a pipe)."""

    def __init__(self, q: queue.Queue[object]):
        self._q = q

    def __iter__(self):
        while True:
            item = self._q.get()
            if item is None:  # explicit EOF
                return
            yield item


class _FakePopen:
    def __init__(self, behavior, *, die_after=None):
        self.pid = 2_147_483_647
        self._out_q: queue.Queue[object] = queue.Queue()
        self._err_q: queue.Queue[object] = queue.Queue()
        self._err_q.put(None)  # stderr closes immediately (no diagnostics)
        self.sent: list[object] = []
        self.stdin = _FakeStdin(self._out_q, self.sent, behavior)
        self.stdout = _BlockingLines(self._out_q)
        self.stderr = _BlockingLines(self._err_q)
        self.returncode = None
        self._terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self._terminated = True
        self.returncode = 0
        self._out_q.put(None)

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self.terminate()


def _ok_behavior(text: str):
    """Echo-style success: system init, assistant, result."""
    return [
        {"type": "system", "subtype": "init", "session_id": "sess-1"},
        {"type": "assistant",
         "message": {"role": "assistant",
                     "content": [{"type": "text", "text": f"echo:{text}"}]}},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": f"echo:{text}", "session_id": "sess-1"},
    ]


def _patch_popen(monkeypatch, factory):
    monkeypatch.setattr(claude_session.subprocess, "Popen",
                        lambda *a, **k: factory())


def test_ask_returns_result_text(monkeypatch):
    _patch_popen(monkeypatch, lambda: _FakePopen(_ok_behavior))
    s = ClaudeStreamSession(model="sonnet")
    assert s.ask("hello") == "echo:hello"
    assert s._session_id == "sess-1"
    s.close()


def test_only_new_turn_is_sent(monkeypatch):
    """Persistent session sends just the new user text each turn (claude keeps
    the conversation), not a re-flattened history."""
    fake = _FakePopen(_ok_behavior)
    monkeypatch.setattr(claude_session.subprocess, "Popen", lambda *a, **k: fake)
    s = ClaudeStreamSession()
    s.ask("first")
    s.ask("second")
    assert fake.sent == ["first", "second"]
    s.close()


def test_on_text_callback_fires(monkeypatch):
    _patch_popen(monkeypatch, lambda: _FakePopen(_ok_behavior))
    s = ClaudeStreamSession()
    seen: list[str] = []
    s.ask("hi", on_text=seen.append)
    assert seen == ["echo:hi"]
    s.close()


def test_error_result_is_reported(monkeypatch):
    def err_behavior(text: str):
        return [
            {"type": "system", "session_id": "s"},
            {"type": "result", "subtype": "error_during_execution",
             "is_error": True, "result": "boom"},
        ]
    _patch_popen(monkeypatch, lambda: _FakePopen(err_behavior))
    s = ClaudeStreamSession()
    out = s.ask("trigger")
    assert "boom" in out and out.startswith("[birkin] Claude error")
    s.close()


def test_restart_on_dead_process(monkeypatch):
    """If the process exited, ask() restarts once and still returns a reply."""
    calls = {"n": 0}

    class _DeadOnce(_FakePopen):
        def __init__(self):
            super().__init__(_ok_behavior)
            calls["n"] += 1
            if calls["n"] == 1:
                # Simulate immediate death: stdout EOF, poll() reports exited.
                self.returncode = 1
                self._out_q.put(None)

    monkeypatch.setattr(claude_session.subprocess, "Popen",
                        lambda *a, **k: _DeadOnce())
    s = ClaudeStreamSession()
    assert s.ask("hi") == "echo:hi"
    assert calls["n"] >= 2  # restarted at least once
    s.close()


def test_empty_input_short_circuits(monkeypatch):
    _patch_popen(monkeypatch, lambda: _FakePopen(_ok_behavior))
    s = ClaudeStreamSession()
    assert s.ask("   ") == ""
    s.close()


def test_assistant_text_extraction():
    ev = {"message": {"content": [
        {"type": "text", "text": "a"},
        {"type": "tool_use", "name": "x"},
        {"type": "text", "text": "b"}]}}
    assert claude_session._assistant_text(ev) == "ab"
    assert claude_session._assistant_text({"message": {"content": "raw"}}) == "raw"
    assert claude_session._assistant_text({}) == ""


def test_system_prompt_written_to_tempfile(monkeypatch):
    captured = {}

    def factory():
        return _FakePopen(_ok_behavior)

    def fake_popen(argv, *a, **k):
        captured["argv"] = argv
        return factory()

    monkeypatch.setattr(claude_session.subprocess, "Popen", fake_popen)
    s = ClaudeStreamSession(append_system_prompt="You are birkin.\n& special | chars")
    s.ask("hi")
    argv = captured["argv"]
    assert "--append-system-prompt-file" in argv
    idx = argv.index("--append-system-prompt-file")
    path = argv[idx + 1]
    import pathlib
    assert pathlib.Path(path).read_text(encoding="utf-8").startswith("You are birkin.")
    s.close()
    assert not pathlib.Path(path).exists()  # cleaned up


def test_enforced_warm_session_uses_only_birkin_mcp_tools():
    session = ClaudeStreamSession(birkin_mcp=True)
    session.egress_enforced = True

    argv = session._build_argv()
    mcp_index = argv.index("--mcp-config")
    with open(argv[mcp_index + 1], encoding="utf-8") as handle:
        mcp = json.load(handle)

    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--allowedTools") + 1] == "mcp__birkin__*"
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert "--disable-slash-commands" in argv
    assert "--no-chrome" in argv
    assert "--no-session-persistence" in argv
    assert "--dangerously-skip-permissions" not in argv
    assert set(mcp["mcpServers"]) == {"birkin"}
    session.close()


def test_send_raises_without_process():
    """_send must raise (not assert, stripped under -O) when there's no proc."""
    s = ClaudeStreamSession()
    with pytest.raises(claude_session.ClaudeSessionError):
        s._send("hi")


def test_drain_never_blocks_on_full_queue():
    """The 'out' drain must drop the oldest stale event rather than block when
    the bounded queue fills (the C2 deadlock fix). If it blocked, this hangs."""
    q: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=2)
    lines = [f"line{i}\n" for i in range(12)]
    claude_session.ClaudeStreamSession._drain(iter(lines), "out", q)
    items = []
    while not q.empty():
        items.append(q.get_nowait())
    assert ("out", None) in items     # the closed sentinel survived
    assert len(items) <= 2            # only the newest were kept


def test_close_reaps_and_is_idempotent(monkeypatch):
    _patch_popen(monkeypatch, lambda: _FakePopen(_ok_behavior))
    s = ClaudeStreamSession()
    s.ask("hi")
    s.close()                 # reaps the fake (wait/kill) without raising
    assert not s.is_alive()
    s.close()                 # second close is a no-op


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
