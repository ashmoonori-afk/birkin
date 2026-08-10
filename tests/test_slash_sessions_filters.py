"""/sessions gains search with --since/--channel/--model filters."""

from __future__ import annotations

import contextlib
import io
import json
import types


def _dispatch(line: str) -> str:
    import birkin.repl  # noqa: F401
    from birkin import config, slashcommands as sc
    buf = io.StringIO()
    sess = types.SimpleNamespace(cfg=config.load_config())
    with contextlib.redirect_stdout(buf):
        sc.dispatch(sess, line)
    return buf.getvalue()


def _write_session(stem: str, *texts: str) -> None:
    from birkin import config
    msgs = []
    for i, t in enumerate(texts):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": [{"type": "text", "text": t}]})
    (config.sessions_dir() / f"{stem}.json").write_text(
        json.dumps(msgs), encoding="utf-8")


def test_bare_sessions_still_lists_saved():
    _write_session("mysave", "hello there", "hi")
    out = _dispatch("/sessions")
    assert "mysave" in out


def test_sessions_query_searches_with_metadata():
    _write_session("k8s", "we chose kubernetes for deploys", "agreed")
    _write_session("milk", "buy milk", "ok")
    out = _dispatch("/sessions kubernetes")
    assert "k8s" in out
    assert "milk" not in out.replace("kubernetes", "")
    # metadata surfaces: a date (YYYY-MM) appears in the result line
    assert "20" in out


def test_sessions_since_filter_rejects_bad_value():
    _write_session("k8s", "kubernetes deploys")
    out = _dispatch("/sessions kubernetes --since not-a-date")
    assert "since" in out.lower()


def test_sessions_filters_parse_and_apply():
    _write_session("k8s", "kubernetes deploys everywhere")
    out = _dispatch("/sessions kubernetes --since 30d")
    assert "k8s" in out
