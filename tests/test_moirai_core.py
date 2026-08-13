"""Moirai core: bindings decided before the run, journal, resume, executors.

The engine's whole claim is that control flow is deterministic and that *who*
answers each call is settled before anything spawns. These tests hold both:
the ladder resolves without I/O, an impossible binding dies at launch rather
than at agent eight, and a resumed run replays until the first thing that
actually changed.

No live models here — `spawn` is injected. Real provider calls live in
test_moirai_live.py.
"""

from __future__ import annotations

import json
import threading

import pytest

from birkin import moirai
from birkin.moirai import bindings as B
from birkin.moirai import journal


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _write(tmp_path, body: str, name: str = "wf.py"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


SIMPLE = '''
meta = {"name": "simple", "description": "d",
        "roles": {"worker": {"default": "codex:gpt-5.6-sol"}}}

def main(m):
    return m.agent("hello", role="worker")
'''


# ---------------- spec + ladder -------------------------------------------

@pytest.mark.parametrize("spec,expect", [
    ("codex:gpt-5.6-sol", ("codex", "gpt-5.6-sol")),
    ("claude:opus", ("claude", "opus")),
    ("claude-cli:haiku", ("claude", "haiku")),        # -cli suffix tolerated
    ("codex", ("codex", "")),                          # provider default
    ("  anthropic:claude-sonnet-4-6  ", ("anthropic", "claude-sonnet-4-6")),
])
def test_parse_spec(spec, expect):
    assert B.parse_spec(spec) == expect


@pytest.mark.parametrize("bad", ["", "   ", ":model"])
def test_parse_spec_rejects_junk(bad):
    with pytest.raises(B.BindingError):
        B.parse_spec(bad)


def test_parse_cli_binds_and_its_error():
    assert B.parse_cli_binds(["critic=claude:opus", "w=codex"]) == {
        "critic": "claude:opus", "w": "codex"}
    with pytest.raises(B.BindingError):
        B.parse_cli_binds(["nonsense"])


def test_roles_may_be_declared_as_a_bare_string():
    assert B.declared_roles({"roles": {"critic": "claude:haiku"}}) == {
        "critic": {"default": "claude:haiku"}}


def test_ladder_prefers_cli_over_picker_over_last_over_config_over_meta():
    roles = {"critic": {"default": "claude:haiku"}}
    cfg = {"moirai_roles": {"critic": "claude:sonnet"},
           "provider": "codex-cli", "model": "gpt-5.6-sol"}

    def spec(**kw):
        return B.resolve(roles, cfg=cfg, **kw)["critic"].spec

    assert spec(cli={"critic": "claude:opus"},
                picked={"critic": "claude:sonnet"}) == "claude:opus"
    assert spec(picked={"critic": "claude:opus"},
                last={"critic": "claude:haiku"}) == "claude:opus"
    assert spec(last={"critic": "claude:opus"}) == "claude:opus"
    assert spec() == "claude:sonnet"                       # config beats meta
    assert B.resolve(roles, cfg={})["critic"].spec == "claude:haiku"   # meta


def test_ladder_falls_back_to_the_global_provider_for_an_undeclared_default():
    roles = {"worker": {}}                       # no default anywhere
    cfg = {"provider": "codex-cli", "model": "gpt-5.6-sol"}
    b = B.resolve(roles, cfg=cfg)["worker"]
    assert (b.provider, b.model, b.source) == ("codex", "gpt-5.6-sol", "global")


def test_ladder_reports_where_each_binding_came_from():
    roles = {"a": {"default": "claude:haiku"}, "b": {"default": "codex:x"}}
    got = B.resolve(roles, cli={"a": "claude:opus"}, cfg={})
    assert got["a"].source == "cli" and got["a"].source_label == "--bind"
    assert got["b"].source == "meta"


def test_a_role_with_nothing_to_bind_is_an_error():
    with pytest.raises(B.BindingError, match="바인딩할 모델이 없습니다"):
        B.resolve({"orphan": {}}, cfg={})


# ---------------- launch validation ---------------------------------------

def test_cross_family_bindings_are_refused_before_anything_runs():
    with pytest.raises(B.BindingError, match="claude 계열"):
        B.validate(B.resolve({"r": {"default": "codex:opus"}}, cfg={}))
    with pytest.raises(B.BindingError, match="codex/OpenAI 계열"):
        B.validate(B.resolve({"r": {"default": "claude:gpt-5.6-sol"}}, cfg={}))


def test_unknown_provider_and_bad_tools_are_refused():
    with pytest.raises(B.BindingError, match="모르는 프로바이더"):
        B.validate(B.resolve({"r": {"default": "hal9000:x"}}, cfg={}))
    with pytest.raises(B.BindingError, match="tools는"):
        B.validate(B.resolve(
            {"r": {"default": "codex:gpt-5.6-sol", "tools": "root"}}, cfg={}))


def test_legal_bindings_pass_validation():
    B.validate(B.resolve({
        "a": {"default": "codex:gpt-5.6-sol"},
        "b": {"default": "claude:opus", "tools": "read-only"},
        "c": {"default": "anthropic:claude-sonnet-4-6"},
    }, cfg={}))


def test_using_a_role_the_script_never_declared_is_caught_once(tmp_path):
    p = _write(tmp_path, '''
meta = {"name": "typo", "roles": {"worker": {"default": "codex:x"}}}

def main(m):
    return m.agent("hi", role="wroker")
''')
    script = moirai.load_script(p)
    with pytest.raises(B.BindingError, match="선언되지 않은 role"):
        B.check_roles_used(script.roles, script.roles_used())


# ---------------- loader ---------------------------------------------------

def test_loader_reads_meta_roles_and_main(tmp_path):
    script = moirai.load_script(_write(tmp_path, SIMPLE))
    assert script.name == "simple"
    assert script.roles == {"worker": {"default": "codex:gpt-5.6-sol"}}
    assert script.roles_used() == {"worker"}
    assert script.estimated_calls() == {"worker": 1}
    assert len(script.sha256) == 64


@pytest.mark.parametrize("body,match", [
    ("meta = {}\ndef main(m): pass", "name"),
    ('meta = {"name": "x"}', "main"),
    ("this is not python(", "로드 실패"),
])
def test_loader_refuses_a_malformed_script(tmp_path, body, match):
    with pytest.raises(moirai.MoiraiError, match=match):
        moirai.load_script(_write(tmp_path, body))


def test_loader_reports_a_missing_file(tmp_path):
    with pytest.raises(moirai.MoiraiError, match="없습니다"):
        moirai.load_script(tmp_path / "nope.py")


# ---------------- running --------------------------------------------------

def _spawn_echo(calls):
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        calls.append((prompt, binding.spec))
        return f"answer to {prompt}"
    return spawn


def test_a_run_records_bindings_agents_and_a_result(tmp_path):
    calls = []
    script = moirai.load_script(_write(tmp_path, SIMPLE))
    out = moirai.run_script(script, cfg={}, spawn=_spawn_echo(calls))
    assert out["status"] == "completed" and out["agents"] == 1
    assert out["result"] == "answer to hello"
    assert calls == [("hello", "codex:gpt-5.6-sol")]

    run = journal.get_run(out["run_id"])
    assert run["status"] == "completed"
    assert json.loads(run["bindings_json"]) == {"worker": "codex:gpt-5.6-sol"}


def test_concurrent_calls_never_spawn_above_the_agent_cap(tmp_path):
    entered = 0
    entered_lock = threading.Lock()
    release = threading.Event()

    def blocking_spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        nonlocal entered
        with entered_lock:
            entered += 1
        assert release.wait(timeout=10)
        return prompt

    script = moirai.load_script(_write(tmp_path, '''
meta = {"name": "parallel-cap", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return m.parallel(
        [lambda i=i: m.agent(str(i), role="w") for i in range(8)],
    )
'''))
    outcome = {}

    def run():
        outcome.update(moirai.run_script(
            script,
            cfg={"moirai_max_agents": 2},
            spawn=blocking_spawn,
        ))

    thread = threading.Thread(target=run)
    thread.start()
    deadline = threading.Event()
    for _ in range(1000):
        with entered_lock:
            if entered >= 2:
                break
        deadline.wait(0.001)
    release.set()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert entered == 2
    assert outcome["agents"] == 2


def test_an_explicit_provider_on_the_call_overrides_the_role(tmp_path):
    calls = []
    p = _write(tmp_path, '''
meta = {"name": "override", "roles": {"w": {"default": "codex:gpt-5.6-sol"}}}

def main(m):
    return m.agent("x", role="w", provider="claude", model="opus")
''')
    moirai.run_script(moirai.load_script(p), cfg={}, spawn=_spawn_echo(calls))
    assert calls == [("x", "claude:opus")]


def test_a_failing_agent_yields_none_without_killing_the_run(tmp_path):
    def boom(prompt, binding, opts, cfg, *, timeout=900.0):
        raise RuntimeError("provider exploded")

    p = _write(tmp_path, '''
meta = {"name": "resilient", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return {"got": m.agent("a", role="w")}
''')
    out = moirai.run_script(moirai.load_script(p), cfg={}, spawn=boom)
    assert out["status"] == "completed" and out["result"] == {"got": None}


def test_a_provider_error_string_counts_as_failure(tmp_path):
    def err(prompt, binding, opts, cfg, *, timeout=900.0):
        return "[provider-error] codex not logged in"

    p = _write(tmp_path, '''
meta = {"name": "perr", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return m.agent("a", role="w")
''')
    out = moirai.run_script(moirai.load_script(p), cfg={}, spawn=err)
    assert out["result"] is None
    assert journal.run_calls(out["run_id"])[0]["status"] == "error"


def test_parallel_preserves_order_and_isolates_failures(tmp_path):
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if prompt == "b":
            raise RuntimeError("nope")
        return prompt.upper()

    p = _write(tmp_path, '''
meta = {"name": "par", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return m.parallel([lambda t=t: m.agent(t, role="w") for t in "abc"])
''')
    out = moirai.run_script(moirai.load_script(p), cfg={}, spawn=spawn)
    assert out["result"] == ["A", None, "C"]


def test_pipeline_runs_each_item_through_every_stage(tmp_path):
    p = _write(tmp_path, '''
meta = {"name": "pipe", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return m.pipeline(
        ["x", "y"],
        lambda item, *_: m.agent(f"one:{item}", role="w"),
        lambda prev, *_: m.agent(f"two:{prev}", role="w"),
    )
''')
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        return prompt

    out = moirai.run_script(moirai.load_script(p), cfg={}, spawn=spawn)
    assert out["result"] == ["two:one:x", "two:one:y"]


def test_the_spawn_cap_stops_a_runaway_script(tmp_path):
    p = _write(tmp_path, '''
meta = {"name": "runaway", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return [m.agent(str(i), role="w") for i in range(10)]
''')
    out = moirai.run_script(moirai.load_script(p), cfg={"moirai_max_agents": 3},
                            spawn=_spawn_echo([]))
    assert out["agents"] == 3
    assert out["result"].count(None) == 7


def test_an_abort_stops_further_agents(tmp_path):
    import threading
    flag = threading.Event()

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        flag.set()                       # first agent trips the abort
        return "ok"

    p = _write(tmp_path, '''
meta = {"name": "abortable", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return [m.agent(str(i), role="w") for i in range(4)]
''')
    out = moirai.run_script(moirai.load_script(p), cfg={}, spawn=spawn,
                            abort=flag)
    assert out["status"] == "aborted"
    assert out["agents"] == 1 and out["result"][1:] == [None, None, None]


def test_verify_routes_the_active_goal_gate_to_shell_approval(tmp_path):
    from birkin import goals, store

    goals.set_goal("Verify workflow")
    marker = tmp_path / "must-not-exist"
    command = f"echo bad > {marker}"
    p = _write(tmp_path, f'''
meta = {{"name": "verified"}}

def main(m):
    return m.verify({command!r})
''')

    out = moirai.run_script(moirai.load_script(p), cfg={"auto_approve": []})

    assert out["result"] is None
    assert not marker.exists()
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["category"] == "shell"
    assert pending[0]["payload"]["command"] == command


def test_tool_bearing_agents_are_refused_until_m3(tmp_path):
    p = _write(tmp_path, '''
meta = {"name": "tools", "roles": {"w": {"default": "codex:x", "tools": "read-only"}}}

def main(m):
    return m.agent("read the repo", role="w")
''')
    out = moirai.run_script(moirai.load_script(p), cfg={})
    assert out["result"] is None            # refused, run survives
    assert "M3" in journal.run_calls(out["run_id"])[0]["error"]


# ---------------- journal + resume ----------------------------------------

def test_call_key_ignores_cosmetics_but_not_the_model():
    base = {"provider": "codex", "model": "a", "tools": "none"}
    assert journal.call_key("p", base) == journal.call_key("p", dict(base))
    assert journal.call_key("p", base) != journal.call_key(
        "p", {**base, "model": "b"})


def test_resume_replays_matching_calls_and_reruns_the_rest(tmp_path):
    p = _write(tmp_path, '''
meta = {"name": "resumable", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return [m.agent("first", role="w"), m.agent(m.args["second"], role="w")]
''')
    script = moirai.load_script(p)
    live = []

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        live.append(prompt)
        return f"R:{prompt}"

    first = moirai.run_script(script, cfg={}, args={"second": "b1"},
                              spawn=spawn)
    assert live == ["first", "b1"]

    live.clear()
    second = moirai.run_script(script, cfg={}, args={"second": "b2"},
                               spawn=spawn, resume_from=first["run_id"])
    assert live == ["b2"], "unchanged call should have replayed from cache"
    assert second["cache_hits"] == 1
    assert second["result"] == ["R:first", "R:b2"]


def test_changing_one_role_binding_only_misses_that_role(tmp_path):
    p = _write(tmp_path, '''
meta = {"name": "rebind",
        "roles": {"a": {"default": "codex:x"}, "b": {"default": "claude:haiku"}}}

def main(m):
    return [m.agent("one", role="a"), m.agent("two", role="b")]
''')
    script = moirai.load_script(p)
    live = []

    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        live.append((prompt, binding.spec))
        return "ok"

    first = moirai.run_script(script, cfg={}, spawn=spawn)
    live.clear()

    rebound = B.resolve(script.roles, cli={"b": "claude:opus"}, cfg={})
    moirai.run_script(script, cfg={}, bindings_map=rebound, spawn=spawn,
                      resume_from=first["run_id"])
    assert live == [("two", "claude:opus")], (
        "only the rebound role should have re-run")


def test_observed_latency_is_none_until_something_has_run():
    assert journal.observed("codex", "never-used") is None


def test_observed_latency_appears_after_a_run(tmp_path):
    script = moirai.load_script(_write(tmp_path, SIMPLE))
    moirai.run_script(script, cfg={}, spawn=_spawn_echo([]))
    seen = journal.observed("codex", "gpt-5.6-sol")
    assert seen is not None and seen["n"] == 1 and seen["seconds"] >= 0


def test_last_bindings_feeds_the_next_run(tmp_path):
    script = moirai.load_script(_write(tmp_path, SIMPLE))
    moirai.run_script(script, cfg={}, spawn=_spawn_echo([]))
    assert journal.last_bindings("simple") == {"worker": "codex:gpt-5.6-sol"}


def test_a_run_is_visible_to_the_existing_audit_trail(tmp_path):
    from birkin import store
    script = moirai.load_script(_write(tmp_path, SIMPLE))
    out = moirai.run_script(script, cfg={}, spawn=_spawn_echo([]))
    runs = [r for r in store.list_runs(limit=10) if r.get("kind") == "moirai"]
    assert runs and out["run_id"] in json.dumps(runs[0], ensure_ascii=False)
