"""Slash wiring for persisted goals: /goal set|show|pause|done."""

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


def test_goal_set_persists_and_show_renders_budget():
    from birkin import goals
    out = _dispatch('/goal set Birkin 보고서 완성 --budget 12000')
    state = goals.get_active()
    assert state is not None
    assert state.objective == "Birkin 보고서 완성"
    assert state.budget_tokens == 12000
    assert "Birkin 보고서 완성" in out

    shown = _dispatch("/goal show")
    assert "12" in shown  # budget surfaced


def test_goal_pause_and_done_transition_state():
    from birkin import goals
    _dispatch("/goal set finish the report")
    _dispatch("/goal pause")
    state = goals.get_active()
    assert state is None or state.status != "active"

    _dispatch("/goal set finish the report")
    _dispatch("/goal done")
    assert goals.get_active() is None


def test_goal_gate_command_is_stored_not_executed():
    from birkin import goals, store
    _dispatch('/goal set risky --gate "echo pwned > /tmp/x"')
    state = goals.get_active()
    assert state is not None
    assert state.gate_cmd == "echo pwned > /tmp/x"
    # setting a gate must not execute anything nor queue an approval yet
    assert store.list_pending() == []


def test_goal_without_args_prints_usage():
    out = _dispatch("/goal")
    assert "/goal" in out
