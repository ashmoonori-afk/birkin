"""Past-conversation recall tools (session_search / session_get)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from birkin import config, sessions_index
from birkin.tools import ToolContext, build_registry, sessions


def _write_session(stem: str, *texts: str, metadata=None,
                   date: str | None = None) -> None:
    msgs = []
    for i, t in enumerate(texts):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": [{"type": "text", "text": t}]})
    payload = {"metadata": metadata, "messages": msgs} if metadata else msgs
    path = config.sessions_dir() / f"{stem}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    if date:
        timestamp = datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()
        os.utime(path, (timestamp, timestamp))


def _tool(name: str):
    return next(t for t in sessions.tools() if t.name == name)


def test_search_finds_matching_session_with_snippet():
    _write_session("s1", "let's use kubernetes for deploys", "agreed")
    _write_session("s2", "buy milk", "ok")
    hits = sessions.search_sessions("kubernetes deploys")
    assert hits and hits[0]["session"] == "s1"
    assert "kubernetes" in hits[0]["snippet"]


def test_search_korean_roundtrip():
    _write_session("kr", "메모리 팰리스 구역 설계를 논의했다", "네 정리했습니다")
    hits = sessions.search_sessions("구역 설계")
    assert hits and hits[0]["session"] == "kr"


def test_search_tool_requires_query_and_reports_no_match():
    res = _tool("session_search").fn({"query": ""}, None)
    assert res.is_error
    res = _tool("session_search").fn({"query": "zzzznothing"}, None)
    assert not res.is_error and "No past sessions" in res.content


def test_metadata_filters_compose_with_ranking_and_since():
    _write_session("old-telegram", "redis redis redis redis",
                   metadata={"source": "telegram", "model": "sonnet"},
                   date="2026-07-01")
    _write_session("new-repl", "redis redis redis",
                   metadata={"source": "repl", "model": "gpt-5.6-sol"},
                   date="2026-08-02")
    _write_session("new-telegram", "redis",
                   metadata={"source": "telegram", "model": "gpt-5.6-sol"},
                   date="2026-08-03")

    hits = sessions.search_sessions(
        "redis", limit=1, since="2026-08-01", channel="telegram",
        model="gpt-5.6-sol")

    assert [hit["session"] for hit in hits] == ["new-telegram"]
    assert hits[0]["channel"] == "telegram"
    assert hits[0]["model"] == "gpt-5.6-sol"


def test_scan_fallback_keeps_dict_shape_and_applies_filters(monkeypatch):
    _write_session("telegram", "memory palace",
                   metadata={"source": "telegram", "model": "sonnet"})
    _write_session("repl", "memory palace",
                   metadata={"source": "repl", "model": "sonnet"})
    monkeypatch.setattr(sessions_index, "search", lambda *args, **kwargs: None)

    hits = sessions.search_sessions("memory", channel="telegram")

    assert [h["session"] for h in hits] == ["telegram"]
    assert set(hits[0]) == {
        "session", "date", "channel", "model", "snippet", "score"}


def test_session_search_tool_exposes_filters_and_renders_metadata():
    _write_session("meta", "kubernetes deploys",
                   metadata={"source": "telegram", "model": "sonnet"},
                   date="2026-08-02")
    tool = _tool("session_search")
    assert {"since", "channel", "model"} <= set(
        tool.input_schema["properties"])

    res = tool.fn({"query": "kubernetes", "since": "2026-08-01",
                   "channel": "telegram", "model": "sonnet"}, None)

    assert not res.is_error
    assert "2026-08-02" in res.content
    assert "telegram" in res.content
    assert "score=" in res.content


def test_session_get_returns_transcript_and_rejects_paths():
    _write_session("readme", "unique payload here", "noted")
    assert "unique payload" in sessions.get_session("readme")
    assert "unique payload" in sessions.get_session("readme.json")
    assert sessions.get_session("../secrets") is None
    res = _tool("session_get").fn({"session": "missing"}, None)
    assert res.is_error


def test_registry_exposes_sessions_group():
    from pathlib import Path
    ctx = ToolContext(cfg={}, client=None, cwd=Path.cwd())
    names = build_registry(ctx, include={"sessions"}).names()
    assert set(names) == {"session_search", "session_get"}
