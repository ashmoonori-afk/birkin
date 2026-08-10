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
    from birkin import agentruns
    rec = agentruns.register_run("scan arxiv for transformers")
    out = _dispatch("/agents")
    assert rec["id"][:8] in out
    assert "running" in out


def test_agents_with_no_runs_says_so():
    out = _dispatch("/agents")
    assert "No agent runs" in out


def test_attach_shows_run_status_and_task():
    from birkin import agentruns
    rec = agentruns.register_run("summarize the vault")
    out = _dispatch(f"/attach {rec['id']}")
    assert "summarize the vault" in out
    assert "running" in out


def test_attach_unknown_id_errors():
    out = _dispatch("/attach zzz-not-a-run")
    assert "No run" in out


def test_send_appends_to_inbox():
    from birkin import agentruns
    rec = agentruns.register_run("long research task")
    out = _dispatch(f"/send {rec['id']} 결론만 줘")
    assert "queued" in out.lower() or "Queued" in out
    assert agentruns.drain_messages(rec["id"]) == ["결론만 줘"]


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
