"""Deterministic tests for change-only cron monitors."""

from __future__ import annotations

import hashlib

from birkin import monitor


class _Response:
    def __init__(self, content: bytes):
        self.content = content
        self.read_sizes: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self.content[:size]


class _Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def open(self, request, **kwargs):
        self.calls.append((request, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_ssrf_blocked_url_is_rejected_without_fetching(monkeypatch):
    fetched = []
    monkeypatch.setattr(
        monitor.urllib.request, "build_opener",
        lambda *args: fetched.append(args),
    )

    result = monitor.check({
        "id": "blocked", "monitor_url": "http://127.0.0.1/private"
    })

    assert result.changed is False
    error = (result.error or "").lower()
    assert "blocked" in error or "refused" in error or "https" in error
    assert fetched == []


def test_url_fetch_is_bounded_and_initial_check_sets_baseline(monkeypatch):
    response = _Response(b"abcdef")
    opener = _Opener([response])
    monkeypatch.setattr(monitor.urllib.request, "build_opener", lambda *a: opener)
    monkeypatch.setattr(monitor, "_is_blocked_url", lambda url: False)

    result = monitor.check({
        "id": "bounded", "monitor_url": "https://example.test/page",
        "max_bytes": 3,
    })

    assert result.changed is False
    assert result.error is None
    assert result.content_tail == "abc"
    assert response.read_sizes == [3]
    assert opener.calls[0][1]["timeout"] == 30
    state = monitor.load_state("bounded")
    assert state["last_hash"] == hashlib.sha256(b"abc").hexdigest()
    assert state["last_checked"]
    assert state["last_changed"] is None
    assert state["last_error"] is None


def test_url_fetch_uses_the_shared_pinned_opener(monkeypatch):
    response = _Response(b"bounded")
    opener = _Opener([response])
    calls = []
    monkeypatch.setattr(
        monitor,
        "pinned_opener",
        lambda: calls.append(True) or opener,
        raising=False,
    )
    monkeypatch.setattr(
        monitor.urllib.request,
        "build_opener",
        lambda *_args: opener,
    )
    monkeypatch.setattr(monitor, "_is_blocked_url", lambda _url: False)

    assert monitor._fetch_url("https://example.test/page", 4) == b"boun"
    assert calls == [True]


def test_error_does_not_change_hash(monkeypatch):
    first = _Response(b"baseline")
    opener = _Opener([first, OSError("offline")])
    monkeypatch.setattr(monitor.urllib.request, "build_opener", lambda *a: opener)
    monkeypatch.setattr(monitor, "_is_blocked_url", lambda url: False)
    job = {"id": "stable", "monitor_url": "https://example.test"}

    monitor.check(job)
    before = monitor.load_state("stable")["last_hash"]
    result = monitor.check(job)
    after = monitor.load_state("stable")

    assert result.changed is False
    assert result.error == "offline"
    assert after["last_hash"] == before
    assert after["last_error"] == "offline"
    assert after["last_checked"]


def test_changed_content_returns_context_and_updates_state(monkeypatch):
    opener = _Opener([_Response(b"old"), _Response(b"new content")])
    monkeypatch.setattr(monitor.urllib.request, "build_opener", lambda *a: opener)
    monkeypatch.setattr(monitor, "_is_blocked_url", lambda url: False)
    job = {"id": "changed", "monitor_url": "https://example.test"}

    assert monitor.check(job).changed is False
    result = monitor.check(job)

    assert result.changed is True
    assert result.error is None
    assert "SHA-256" in result.diff_context
    assert len(result.diff_context) <= 4000
    assert result.content_tail == "new content"
    assert len(result.content_tail) <= 8000
    state = monitor.load_state("changed")
    assert state["last_changed"]
    assert state["last_error"] is None


def test_monitor_script_uses_shell_policy_and_hashes_stdout_plus_stderr(
        monkeypatch):
    captured = {}

    def fake_run(request):
        captured["request"] = request

        class Result:
            stdout = "out"
            stderr = "err"
            returncode = 0

        return Result()

    monkeypatch.setattr(monitor, "run_shell_command", fake_run)
    result = monitor.check({"id": "script", "monitor_script": "echo check"})

    assert result.error is None
    request = captured["request"]
    assert request.command == "echo check"
    assert request.timeout == 600
    assert monitor.load_state("script")["last_hash"] == hashlib.sha256(
        b"outerr"
    ).hexdigest()
