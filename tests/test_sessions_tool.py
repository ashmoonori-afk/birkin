"""Past-conversation recall tools (session_search / session_get)."""

from __future__ import annotations

import json

from birkin import config
from birkin.tools import ToolContext, build_registry, sessions


def _write_session(stem: str, *texts: str) -> None:
    msgs = []
    for i, t in enumerate(texts):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": [{"type": "text", "text": t}]})
    (config.sessions_dir() / f"{stem}.json").write_text(
        json.dumps(msgs), encoding="utf-8")


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
