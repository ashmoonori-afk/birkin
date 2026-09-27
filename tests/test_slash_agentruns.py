"""Slash wiring for durable agent runs: /agents, /attach, /send."""

from __future__ import annotations

import contextlib
import io
import types


def _dispatch(line: str) -> str:
    import birkin.repl  # noqa: F401  (registers every command)
    from birkin import config, slashcommands as sc
    buf = io.StringIO()
    sess = types.SimpleNamespace(cfg=config.load_config())
    with contextlib.redirect_stdout(buf):
        sc.dispatch(sess, line)
    return buf.getvalue()


def test_agents_lists_registered_runs():
    from birkin import agentruns, slashcommands as sc
    rec = agentruns.register_run("scan arxiv for transformers")
    out = _dispatch("/agents")
    assert rec["id"][:8] in out
    assert sc._RUN_STATUS_LABELS["running"] in out
    assert "hb " not in out and "running" not in out


def test_agents_with_no_runs_says_so():
    out = _dispatch("/agents")
    assert "/summon" in out and "No agent runs" not in out


def test_agents_columns_align_with_korean_tasks():
    from birkin import agentruns, ui
    agentruns.register_run("scan arxiv for transformers")
    agentruns.register_run("경쟁사 세 곳의 가격 정책을 조사하고 표로 정리해 주세요")
    out = _dispatch("/agents")

    widths = []
    for start in ("scan arxiv", "경쟁사 세 곳"):
        (line,) = [ln for ln in out.splitlines() if start in ln]
        widths.append(ui.cell_width(line[:line.index(start)]))
    assert widths[0] == widths[1]


def test_agents_shows_duration_not_heartbeat_for_finished_runs():
    from birkin import agentruns
    rec = agentruns.register_run("summarize the vault")
    agentruns.finish_run(rec["id"], "done", "ok")
    out = _dispatch("/agents")
    assert "완료" in out and "걸림" in out and "hb " not in out


def test_agents_marks_a_dead_worker_as_unresponsive():
    from birkin import agentruns
    rec = agentruns.register_run("dead worker")
    agentruns._update(rec["id"], {"last_heartbeat": "2000-01-01T00:00:00+00:00"})
    out = _dispatch("/agents")
    assert "응답 없음" in out and "신호 끊김" in out and "hb " not in out


def test_agents_limits_to_recent_runs():
    from birkin import agentruns
    ids = [agentruns.register_run(f"task {n}")["id"] for n in range(25)]

    recent = _dispatch("/agents")
    assert sum(run_id[:8] in recent for run_id in ids) == 20
    assert all(run_id[:8] in recent for run_id in ids[-20:])
    assert "/agents all" in recent and "5개" in recent

    everything = _dispatch("/agents all")
    assert all(run_id[:8] in everything for run_id in ids)
    assert "생략" not in everything


def test_attach_shows_a_finished_run_without_waiting():
    from birkin import agentruns
    rec = agentruns.register_run("summarize the vault")
    agentruns.finish_run(rec["id"], "done", "vault summary")

    out = _dispatch(f"/attach {rec['id']}")

    assert "summarize the vault" in out
    assert "vault summary" in out


def test_attach_follows_a_live_run_until_it_finishes(monkeypatch):
    import time

    from birkin import agentruns
    rec = agentruns.register_run("long research task")
    agentruns.progress(rec["id"], "tool_start web_search")

    def advance(_seconds):
        agentruns.progress(rec["id"], "tool_end web_search")
        agentruns.finish_run(rec["id"], "done", "the answer")

    monkeypatch.setattr(time, "sleep", advance)
    out = _dispatch(f"/attach {rec['id']}")

    assert "→ web_search" in out    # trail replayed on attach
    assert "← web_search" in out    # and streamed while running
    assert "tool_start" not in out  # never the raw trail event
    assert "the answer" in out      # then the final result


def test_attach_unknown_id_errors():
    out = _dispatch("/attach zzz-not-a-run")
    assert "/agents" in out and "No run" not in out


def test_attach_without_id_shows_usage():
    out = _dispatch("/attach")
    assert "사용법: /attach" in out and "No run" not in out


def test_ambiguous_prefix_asks_for_a_longer_id(monkeypatch):
    import uuid

    from birkin import agentruns
    real_uuid4 = uuid.uuid4
    with monkeypatch.context() as patch:
        # Every id minted here shares the "abc" prefix.
        patch.setattr(uuid, "uuid4", lambda: types.SimpleNamespace(
            hex="abc" + real_uuid4().hex[3:]))
        first = agentruns.register_run("one")
        second = agentruns.register_run("two")

    assert "2개" in _dispatch("/attach abc")
    out = _dispatch("/send abc 계속해")
    assert "2개" in out and "보냈어요" not in out
    assert agentruns.drain_messages(first["id"]) == []
    assert agentruns.drain_messages(second["id"]) == []


def test_send_appends_to_inbox():
    from birkin import agentruns
    rec = agentruns.register_run("long research task")
    out = _dispatch(f"/send {rec['id']} 결론만 줘")
    assert rec["id"][:8] in out and "보냈어요" in out
    assert "Queued" not in out
    assert agentruns.drain_messages(rec["id"]) == ["결론만 줘"]


def test_send_refuses_a_stale_run_by_full_id():
    from birkin import agentruns
    rec = agentruns.register_run("dead worker")
    agentruns._update(rec["id"], {"last_heartbeat": "2000-01-01T00:00:00+00:00"})

    out = _dispatch(f"/send {rec['id']} 계속해")

    assert "응답하지 않아" in out and "보냈어요" not in out
    assert agentruns.drain_messages(rec["id"]) == []


def test_agent_lines_escape_terminal_controls():
    from birkin import agentruns
    hostile = "요약 \x1b]52;c;ZXZpbA==\x07\x1b[2J 끝"
    rec = agentruns.register_run(hostile)
    agentruns.progress(rec["id"], "tool_start \x1b[2Jfake")
    agentruns.finish_run(rec["id"], "done", "결과 \x1b[31m빨강")

    for out in (_dispatch("/agents"), _dispatch(f"/attach {rec['id']}")):
        assert "\x1b" not in out
        assert "\\u001b" in out
        assert "요약" in out


def test_send_requires_id_and_text():
    out = _dispatch("/send")
    assert "usage" in out.lower() or "/send" in out


def test_new_commands_are_grouped_in_help():
    import birkin.repl  # noqa: F401
    from birkin import slashcommands as sc
    grouped: set[str] = set()
    for _title, names in sc._HELP_GROUPS:
        grouped |= set(names)
    for name in ("agents", "attach", "send"):
        assert name in sc._REGISTRY, f"/{name} not registered"
        assert name in grouped, f"/{name} missing from help groups"
