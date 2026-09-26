"""Summonable specialist agents (birkin.summon) and the subagent substrate."""

from __future__ import annotations

import contextlib
import io
import json
import threading
import types

import pytest

from birkin import agentruns, budget, store, summon
from birkin import subagent as subagent_mod
from birkin.agent import ABORTED_NOTICE
from birkin.runtime import build_session


@pytest.fixture(autouse=True)
def _finish_detached_children(monkeypatch):
    # Detached children must end while this test's patches and BIRKIN_HOME are
    # still in place; otherwise they run the real agent loop after teardown and
    # write run records into whichever home is current by then.
    from birkin import slashcommands

    monkeypatch.setattr(slashcommands, "_BACKGROUND_SUMMONS", {})
    before = set(threading.enumerate())
    yield
    for thread in threading.enumerate():
        if thread not in before and thread.name.startswith("birkin-subagent-"):
            thread.join(timeout=10)
            assert not thread.is_alive(), f"{thread.name} outlived its test"


def _session(**extra):
    return build_session({"provider": "codex-cli", "model": "", **extra})


def _write_agent(name: str, text: str):
    directory = summon.agents_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


_VALID = """---
name: contract-reviewer
title: 계약서 검토자
description: 계약서의 위험 조항을 찾아 요약합니다.
tools: [documents, files]
skills: [word-documents]
max_turns: 8
---
You review contracts for risky clauses.
"""


class _ScriptedClient:
    """A provider double: ``replies`` are returned in order, then text."""

    def __init__(self, replies=(), on_call=None):
        self.replies = list(replies)
        self.calls = 0
        self.on_call = on_call

    def complete(self, *, system, messages, tools=None, model=None,
                 on_text=None, abort=None):
        self.calls += 1
        if self.on_call is not None:
            self.on_call(self.calls)
        if self.replies:
            return self.replies.pop(0)
        return {"role": "assistant", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "final answer"}]}


def _tool_call(n: int) -> dict:
    return {"role": "assistant", "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": f"t{n}",
                         "name": "list_files", "input": {}}]}


# -- roster -----------------------------------------------------------------

def test_builtin_roster_is_valid_and_its_skills_exist():
    from birkin import config
    from birkin.skills import build_manager

    skills = build_manager(config.load_config())
    names = [spec.name for spec in summon.BUILTIN_AGENTS]
    assert len(names) == len(set(names))
    for spec in summon.BUILTIN_AGENTS:
        assert summon.NAME_RE.fullmatch(spec.name)
        assert spec.title and spec.description and spec.instructions
        assert set(spec.tools) <= summon.ALLOWED_TOOL_GROUPS
        assert "subagent" not in spec.tools and "shell" not in spec.tools
        assert summon.MIN_TURNS <= spec.max_turns <= summon.MAX_TURNS
        for skill in spec.skills:
            assert skills.get(skill) is not None, (spec.name, skill)


def test_user_definition_is_parsed():
    spec = summon.parse_definition(_VALID, stem="contract-reviewer")
    assert spec.name == "contract-reviewer"
    assert spec.title == "계약서 검토자"
    assert spec.tools == ("documents", "files")
    assert spec.skills == ("word-documents",)
    assert spec.max_turns == 8
    assert spec.source == "user"
    assert "risky clauses" in spec.system_block()


@pytest.mark.parametrize("text, stem, fragment", [
    (_VALID, "other-name", "file name"),
    (_VALID.replace("contract-reviewer", "Contract"), "Contract", "lowercase"),
    (_VALID.replace("description: 계약서의 위험 조항을 찾아 요약합니다.\n", ""),
     "contract-reviewer", "description"),
    (_VALID.replace("You review contracts for risky clauses.\n", ""),
     "contract-reviewer", "instructions"),
    (_VALID.replace("tools: [documents, files]\n", ""),
     "contract-reviewer", "tools"),
    (_VALID.replace("[documents, files]", "[documents, teleport]"),
     "contract-reviewer", "teleport"),
    (_VALID.replace("[documents, files]", "[subagent]"),
     "contract-reviewer", "subagent"),
    (_VALID.replace("[word-documents]", "[a, b, c, d, e]"),
     "contract-reviewer", "skills"),
    (_VALID.replace("max_turns: 8", "max_turns: 0"),
     "contract-reviewer", "max_turns"),
    (_VALID.replace("max_turns: 8", "max_turns: 41"),
     "contract-reviewer", "max_turns"),
    (_VALID.replace("max_turns: 8", "max_turns: true"),
     "contract-reviewer", "max_turns"),
    (_VALID.replace("max_turns: 8", "max_turns: 8\nmodel: --yolo"),
     "contract-reviewer", "model"),
    (_VALID.replace("You review", "x" * 16_001 + " You review"),
     "contract-reviewer", "instructions"),
])
def test_invalid_user_definitions_are_rejected(text, stem, fragment):
    with pytest.raises(summon.SummonError, match=fragment):
        summon.parse_definition(text, stem=stem)


def test_user_agents_extend_but_never_shadow_the_roster():
    _write_agent("contract-reviewer", _VALID)
    _write_agent("researcher", _VALID.replace(
        "contract-reviewer", "researcher"))
    _write_agent("broken", "---\ndescription: x\ntools: [subagent]\n---\nx\n")

    roster, rejected = summon.load_roster()

    assert roster["contract-reviewer"].source == "user"
    assert roster["researcher"].source == "builtin"     # cannot be shadowed
    assert "reserved" in rejected["researcher.md"]
    assert "broken" not in roster
    assert "subagent" in rejected["broken.md"]


@pytest.mark.parametrize("relative", [
    ("agents", "planted.md"),
    ("harness", "harness_state.json"),
    ("sessions", "abc123", "harness", "harness_state.json"),
    # Case variants reach the same directory on case-insensitive volumes.
    ("Agents", "planted.md"),
    ("HARNESS", "harness_state.json"),
    ("sessions", "abc123", "Harness", "harness_state.json"),
])
def test_file_tools_cannot_plant_prompt_or_roster_state(tmp_path, relative):
    from birkin import config
    from birkin.tools import ToolContext, build_registry

    ctx = ToolContext(cfg={}, client=None, cwd=tmp_path)
    target = config.birkin_home().joinpath(*relative)
    res = build_registry(ctx).execute(
        "write_file", {"path": str(target), "content": _VALID})
    # Blocked and routed to a human approval, never written directly.
    assert res.is_error and "control-plane" in str(res.content)
    assert not target.exists()


def test_ordinary_session_files_stay_writable(tmp_path):
    from birkin import config
    from birkin.tools import ToolContext, build_registry

    ctx = ToolContext(cfg={}, client=None, cwd=tmp_path)
    target = config.birkin_home() / "sessions" / "notes.md"
    res = build_registry(ctx).execute(
        "write_file", {"path": str(target), "content": "ok"})
    assert "control-plane" not in str(res.content)


def test_symlinked_and_oversized_definitions_are_rejected(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text(_VALID.replace("contract-reviewer", "linked"),
                       encoding="utf-8")
    summon.agents_dir().mkdir(parents=True, exist_ok=True)
    (summon.agents_dir() / "linked.md").symlink_to(outside)
    _write_agent("huge", _VALID.replace("contract-reviewer", "huge")
                 + "x" * summon.MAX_FILE_BYTES)

    roster, rejected = summon.load_roster()

    assert "linked" not in roster and "regular file" in rejected["linked.md"]
    assert "huge" not in roster and "bytes" in rejected["huge.md"]


def test_get_agent_normalizes_and_explains_misses():
    assert summon.get_agent("@Sheet-Analyst").name == "sheet-analyst"
    with pytest.raises(summon.SummonError, match="available: .*researcher"):
        summon.get_agent("nobody")
    _write_agent("broken", "---\ndescription: x\n---\n")
    with pytest.raises(summon.SummonError, match="invalid"):
        summon.get_agent("broken")


# -- run_subagent with a specialist ------------------------------------------

def _capture_run(monkeypatch):
    seen = {}

    def fake_run(self, user_text, on_text=None, abort=None):
        seen.update(system=self.system, names=set(self.registry.names()),
                    model=self.model, max_turns=self.max_turns,
                    self_improve=self.self_improve,
                    run=agentruns.list_runs()[0])
        return "specialist result"

    monkeypatch.setattr("birkin.agent.Agent.run", fake_run)
    return seen


def test_specialist_gets_role_skills_and_only_its_tool_groups(monkeypatch):
    session = _session(egress={"enabled": True, "enforced": False})
    seen = _capture_run(monkeypatch)

    out = summon.summon("doc-analyst", "요약해줘", session.ctx)

    assert out == "specialist result"
    assert "## Your role: doc-analyst (문서 분석가)" in seen["system"]
    assert "### office-work-os" in seen["system"]           # preloaded
    assert "Available skills" not in seen["system"]         # no load_skill
    assert {"inspect_document", "list_files"} <= seen["names"]
    assert not seen["names"] & {"run_shell", "spawn_subagent", "web_fetch",
                                "load_skill", "m365_mail_send_request"}
    assert seen["max_turns"] == 12
    assert seen["self_improve"] is False
    assert seen["run"]["agent"] == "doc-analyst"
    # Guidance for tools the specialist lacks is not promised to it.
    for absent in ("spawn_subagent", "create_skill", "remember tool",
                   "delegate focused sub-tasks"):
        assert absent not in seen["system"]


def test_specialist_scope_never_widens_the_registry_policy(monkeypatch):
    _write_agent("operator", _VALID.replace("contract-reviewer", "operator")
                 .replace("[documents, files]", "[shell, files, documents]"))
    session = _session(disabled_tools=["documents"],
                       egress={"enabled": True, "enforced": True})
    seen = _capture_run(monkeypatch)

    summon.summon("operator", "run it", session.ctx)

    assert "list_files" in seen["names"]
    assert "run_shell" not in seen["names"]          # enforced egress
    assert "inspect_document" not in seen["names"]   # disabled by the user


def test_specialist_model_override_and_default_inherits_parent(monkeypatch):
    _write_agent("fast", _VALID.replace("contract-reviewer", "fast")
                 .replace("max_turns: 8", "max_turns: 8\nmodel: gpt-5.4-mini"))
    session = _session(model="gpt-5.5", subagent_model="default")
    seen = _capture_run(monkeypatch)

    summon.summon("fast", "go", session.ctx)
    assert seen["model"] == "gpt-5.4-mini"

    summon.summon("planner", "go", session.ctx)
    assert seen["model"] == "gpt-5.5"   # "default" is not sent as a model id


def test_summon_requires_a_task_and_respects_the_token_budget(monkeypatch):
    session = _session(budget_tokens_daily=10)
    _capture_run(monkeypatch)
    with pytest.raises(summon.SummonError, match="task"):
        summon.summon("planner", "   ", session.ctx)
    store.save_run("chat", "earlier", usage={"estTokens": 50})
    with pytest.raises(summon.SummonBudgetExceeded):
        summon.summon("planner", "plan it", session.ctx)


def test_subagent_spend_is_metered_into_the_ledger_and_lease():
    session = _session(subagent_tree_max_tokens=1_000_000)
    client = _ScriptedClient([_tool_call(1), _tool_call(2)])
    session.ctx.client = client

    out = subagent_mod.run_subagent("look around", session.ctx,
                                    reserve_tokens=10)

    assert out == "final answer" and client.calls == 3
    (record,) = [run for run in store.list_runs() if run["kind"] == "subagent"]
    spent = record["usage"]["estTokens"]
    # Three calls, each re-sending the system prompt: far above task+result.
    assert spent > 3 * 500
    assert session.ctx.tree_budget.reserved_tokens == spent


def test_detached_summon_reports_its_run_id(monkeypatch):
    session = _session()
    release = threading.Event()

    def slow(self, user_text, on_text=None, abort=None):
        release.wait(5)
        return "later"

    monkeypatch.setattr("birkin.agent.Agent.run", slow)
    ack = summon.summon("researcher", "look it up", session.ctx, detach=True)
    run_id = summon.detached_run_id(ack)
    assert agentruns.get_run(run_id)["agent"] == "researcher"
    release.set()


# -- control: Esc, console pause, heartbeat -----------------------------------

def test_attached_child_stops_when_the_parent_is_interrupted():
    session = _session()
    client = _ScriptedClient([_tool_call(n) for n in range(1, 10)],
                             on_call=lambda n: session.ctx.abort.set())
    session.ctx.client = client

    out = subagent_mod.run_subagent("long job", session.ctx, max_turns=8)

    assert ABORTED_NOTICE in out
    assert client.calls <= 2


def test_detached_child_is_isolated_from_parent_ui_and_esc(monkeypatch):
    session = _session()
    session.ctx.emit = lambda *a: None
    session.ctx.shell_prompt_cb = lambda *a: "once"
    seen = {}
    real_build = subagent_mod.build_registry

    def spy(ctx, **kwargs):
        seen["ctx"] = ctx
        return real_build(ctx, **kwargs)

    monkeypatch.setattr(subagent_mod, "build_registry", spy)
    monkeypatch.setattr("birkin.agent.Agent.run",
                        lambda self, text, on_text=None, abort=None: "ok")

    subagent_mod.run_subagent("fg", session.ctx)
    assert seen["ctx"].emit is session.ctx.emit
    assert seen["ctx"].shell_prompt_cb is session.ctx.shell_prompt_cb

    assert seen["ctx"].shellguard_approved is session.ctx.shellguard_approved

    subagent_mod.run_subagent("bg", session.ctx, detach=True)
    child = seen["ctx"]
    assert child.emit is None and child.shell_prompt_cb is None
    assert child.shellguard_approved is not session.ctx.shellguard_approved
    session.ctx.abort.set()
    assert not child.abort.is_set()


def test_console_abort_pauses_at_the_next_boundary_until_resume(monkeypatch):
    session = _session()
    state = {"paused_polls": 0}

    def on_call(n):
        if n == 1:
            run = agentruns.list_runs()[0]
            state["id"] = run["id"]
            assert agentruns.control(run["id"], "abort")["ok"]

    def fake_sleep(_seconds):
        state["paused_polls"] += 1
        if state["paused_polls"] == 3:
            assert agentruns.control(state["id"], "resume")["ok"]

    monkeypatch.setattr(subagent_mod, "time", types.SimpleNamespace(
        sleep=fake_sleep, monotonic=__import__("time").monotonic))
    client = _ScriptedClient([_tool_call(1)], on_call=on_call)
    session.ctx.client = client

    out = subagent_mod.run_subagent("pausable", session.ctx)

    assert out == "final answer"
    assert state["paused_polls"] == 3      # held at the boundary, then resumed
    assert agentruns.get_run(state["id"])["status"] == "done"


def test_heartbeat_keeps_a_long_call_from_looking_stale(monkeypatch):
    session = _session()
    beats = threading.Event()
    real_heartbeat = agentruns.heartbeat

    def spy(run_id):
        beats.set()
        return real_heartbeat(run_id)

    monkeypatch.setattr(subagent_mod, "_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(agentruns, "heartbeat", spy)
    monkeypatch.setattr("birkin.agent.Agent.run",
                        lambda self, text, on_text=None, abort=None:
                        "ok" if beats.wait(5) else "no heartbeat")

    assert subagent_mod.run_subagent("slow tool", session.ctx) == "ok"


def test_keyboard_interrupt_finishes_the_durable_record(monkeypatch):
    session = _session()

    def interrupted(self, text, on_text=None, abort=None):
        raise KeyboardInterrupt

    monkeypatch.setattr("birkin.agent.Agent.run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        subagent_mod.run_subagent("ctrl-c", session.ctx)
    assert agentruns.list_runs()[0]["status"] == "error"


def _recording_emit(session, *, fail_on=None):
    events = []

    def emit(event, payload):
        events.append((event, payload))
        if event == fail_on:
            raise RuntimeError("view failed")

    session.ctx.emit = emit
    return events


def test_attached_summon_reports_its_title_to_the_parent_view(monkeypatch):
    session = _session()
    events = _recording_emit(session)
    monkeypatch.setattr("birkin.agent.Agent.run",
                        lambda self, text, on_text=None, abort=None: "ok")

    assert summon.summon("sheet-analyst", "분기 매출 분석", session.ctx) == "ok"

    (start_event, start), (done_event, done) = events
    run_id = agentruns.list_runs()[0]["id"]
    assert (start_event, done_event) == ("subagent.start", "subagent.done")
    for payload in (start, done):
        assert payload["id"] == run_id
        assert payload["agent"] == "sheet-analyst"
        assert payload["agent_title"] == "스프레드시트 분석가"
    assert "is_error" not in done
    assert agentruns.get_run(run_id)["agent_title"] == "스프레드시트 분석가"


def test_failed_attached_summon_closes_its_activity_row(monkeypatch):
    def boom(self, text, on_text=None, abort=None):
        raise RuntimeError("boom")

    monkeypatch.setattr("birkin.agent.Agent.run", boom)
    session = _session()
    events = _recording_emit(session)

    with pytest.raises(RuntimeError, match="boom"):
        summon.summon("sheet-analyst", "분기 매출 분석", session.ctx)

    run_id = agentruns.list_runs()[0]["id"]
    assert [event for event, _payload in events] == [
        "subagent.start", "subagent.done"]
    assert events[-1][1] == {
        "chars": 0, "id": run_id, "agent": "sheet-analyst",
        "agent_title": "스프레드시트 분석가", "is_error": True,
    }
    assert agentruns.get_run(run_id)["status"] == "error"

    # A view that fails while closing the row never masks the run's error.
    failing = _session()
    _recording_emit(failing, fail_on="subagent.done")
    with pytest.raises(RuntimeError, match="boom"):
        summon.summon("sheet-analyst", "분기 매출 분석", failing.ctx)


# -- tree budget per task ----------------------------------------------------

def test_tree_budget_caps_one_task_not_the_whole_session():
    tree = budget.TreeBudget({"subagent_tree_max_nodes": 1,
                              "subagent_tree_max_tokens": 100})
    tree.reserve(tokens=60).settle(tokens=60)
    with pytest.raises(budget.TreeBudgetExceeded, match="node"):
        tree.reserve(tokens=10)

    held = None
    tree.begin_tree()
    held = tree.reserve(tokens=30)         # a detached child keeps its hold
    tree.begin_tree()
    assert tree.nodes == 0 and tree.reserved_tokens == 30
    held.settle(tokens=5)
    assert tree.reserved_tokens == 5


def test_each_chat_turn_starts_a_fresh_tree(monkeypatch):
    session = _session(subagent_tree_max_nodes=1)
    monkeypatch.setattr("birkin.agent.Agent.run",
                        lambda self, text, **kw: "ok")
    session.ctx.tree_budget.nodes = 1
    session.ask("hello", record_turn=False, review_skills=False)
    assert session.ctx.tree_budget.nodes == 0


# -- model-facing tool ------------------------------------------------------

def test_spawn_subagent_summons_a_named_specialist(monkeypatch, tmp_path):
    from birkin.tools import ToolContext
    from birkin.tools import subagent_tool

    seen = {}

    def fake_run(task, ctx, **kwargs):
        seen.update(kwargs)
        return "delegated"

    monkeypatch.setattr(subagent_mod, "run_subagent", fake_run)
    ctx = ToolContext(cfg={}, client=None, cwd=tmp_path)
    tool = next(t for t in subagent_tool.subagent_tools()
                if t.name == "spawn_subagent")

    assert "sheet-analyst" in tool.input_schema["properties"]["agent"][
        "description"]
    res = tool.fn({"task": "check totals", "agent": "sheet-analyst",
                   "skills": ["planning"], "max_turns": 50}, ctx)
    assert not res.is_error
    assert seen["specialist"].name == "sheet-analyst"
    assert seen["skill_names"] == ["spreadsheets", "planning"]
    assert seen["max_turns"] == 12            # the definition caps it

    tool.fn({"task": "t", "agent": "planner"}, ctx)
    assert seen["max_turns"] == 10

    bad = tool.fn({"task": "t", "agent": "nobody"}, ctx)
    assert bad.is_error and "unknown agent" in bad.content


# -- human surfaces ---------------------------------------------------------

def _slash(line: str, session=None) -> str:
    import birkin.repl  # noqa: F401  (registers every command)
    from birkin import config, slashcommands as sc

    buf = io.StringIO()
    sess = session or types.SimpleNamespace(cfg=config.load_config())
    with contextlib.redirect_stdout(buf):
        sc.dispatch(sess, line)
    return buf.getvalue()


def test_slash_summon_lists_shows_and_rejects():
    listing = _slash("/summon")
    assert "소환할 수 있는 에이전트" in listing and "sheet-analyst" in listing
    assert "스프레드시트 분석가" in _slash("/summon sheet-analyst")
    assert "찾을 수 없어요" in _slash("/summon nobody do it")


def test_slash_summon_runs_in_front_and_in_background(monkeypatch):
    session = _session()
    monkeypatch.setattr("birkin.agent.Agent.run",
                        lambda self, text, on_text=None, abort=None: "분석 결과")

    assert "분석 결과" in _slash("/summon sheet-analyst 합계 확인", session)
    out = _slash("/summon --bg researcher 경쟁사 조사", session)
    assert "/attach" in out and "백그라운드" in out
    assert "[researcher]" in _slash("/agents", session)


def test_slash_summon_explains_an_exhausted_budget():
    session = _session(budget_tokens_daily=10)
    store.save_run("chat", "earlier", usage={"estTokens": 50})
    assert "토큰 예산" in _slash("/summon planner 계획", session)


def test_send_refuses_a_finished_run():
    rec = agentruns.register_run("done already")
    agentruns.finish_run(rec["id"], "done", "x")
    out = _slash(f"/send {rec['id']} 하나 더")
    assert "끝나" in out
    assert agentruns.drain_messages(rec["id"]) == []


def test_cli_summon_lists_shows_runs_and_rejects(monkeypatch, capsys):
    from birkin import cli

    assert cli.main(["summon"]) == 0
    assert "meeting-scribe" in capsys.readouterr().out

    assert cli.main(["summon", "--json"]) == 0
    names = {a["name"] for a in json.loads(capsys.readouterr().out)["agents"]}
    assert {"researcher", "report-writer", "mail-drafter"} <= names

    assert cli.main(["summon", "nobody", "x"]) == 2
    assert "찾을 수 없어요" in capsys.readouterr().err

    monkeypatch.setattr("birkin.agent.Agent.run",
                        lambda self, text, on_text=None, abort=None: "회의 정리")
    assert cli.main(["summon", "meeting-scribe", "액션", "아이템"]) == 0
    assert "회의 정리" in capsys.readouterr().out


def test_background_summon_is_announced_once_it_finishes(monkeypatch):
    from birkin import slashcommands as sc

    session = _session()
    release = threading.Event()
    finished = threading.Event()
    real_finish = agentruns.finish_run

    def spy_finish(run_id, status, result=""):
        record = real_finish(run_id, status, result)
        finished.set()
        return record

    monkeypatch.setattr(agentruns, "finish_run", spy_finish)
    monkeypatch.setattr(
        "birkin.agent.Agent.run",
        lambda self, text, on_text=None, abort=None:
        "경쟁사 3곳 비교 완료" if release.wait(5) else "timeout")

    _slash("/summon --bg researcher 경쟁사 조사", session)
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet):
        sc.announce_finished_summons()      # still running: nothing to say
    assert quiet.getvalue() == ""

    release.set()
    assert finished.wait(5)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sc.announce_finished_summons()
        sc.announce_finished_summons()      # announced exactly once
    out = buf.getvalue()
    assert out.count("리서처 작업이 끝났어요") == 1
    assert "경쟁사 3곳 비교 완료" in out


def test_approvals_raised_inside_a_run_are_linked_to_it(monkeypatch):
    from birkin import approvals
    from birkin.web import approval_console

    session = _session()
    queued = {}

    def request_approval(self, text, on_text=None, abort=None):
        queued.update(approvals.propose(
            category="operation", title="보고서 덮어쓰기",
            description="report.docx", payload={"path": "report.docx"},
            cfg={}, origin="conversation"))
        return "승인 대기 중"

    monkeypatch.setattr("birkin.agent.Agent.run", request_approval)
    summon.summon("report-writer", "보고서 갱신", session.ctx)

    run = agentruns.list_runs()[0]
    record = store.get_pending(queued["id"])
    assert record["agent_run_id"] == run["id"]
    assert record["origin"] == "conversation"          # origin untouched
    code, detail = approval_console.run_detail(run["id"])
    assert code == 200 and detail["pending_approvals"] == 1
    assert detail["agent"] == "report-writer"
    # Outside any run nothing is linked.
    outside = approvals.propose(category="operation", title="t",
                                description="d", payload={}, cfg={})
    assert "agent_run_id" not in store.get_pending(outside["id"])


@pytest.mark.parametrize("model", ["gpt-5.5", "claude-haiku-4-5",
                                   "future-provider/model-v1"])
def test_main_prompt_never_promises_delegation_a_preset_removed(model):
    from birkin import promptgate

    cfg = {"model": model, "egress": {"enabled": True, "enforced": False}}
    system = promptgate.compose_main(cfg, persona_text="")
    assert "spawn_subagent" not in system
    assert "delegate focused sub-tasks" not in system


def test_main_prompt_keeps_delegation_when_it_is_available():
    from birkin import promptgate

    cfg = {"model": "claude-opus-4-8",
           "egress": {"enabled": True, "enforced": False}}
    system = promptgate.compose_main(cfg, persona_text="")
    assert "spawn_subagent" in system
    assert "delegate focused sub-tasks" in system


def test_foreground_summon_is_not_killed_by_an_earlier_turns_esc():
    session = _session()
    client = _ScriptedClient()
    session.ctx.client = client
    session.abort.set()            # Esc during the previous chat turn

    out = _slash("/summon planner 계획 세워줘", session)

    assert client.calls == 1
    assert "final answer" in out and "aborted" not in out


def test_cli_backed_specialists_run_read_only_without_birkin_tools(monkeypatch):
    from birkin.llm import LLMClient

    session = _session()             # codex-cli: tools run inside the CLI
    session.client.birkin_mcp = True
    argv = {}

    def capture(self, parts, prompt, abort=None, env=None, on_line=None):
        argv["parts"] = list(parts)
        return "", "", False, False

    monkeypatch.setattr(LLMClient, "_run_cli_capture", capture)

    def run(self, text, on_text=None, abort=None):
        argv["client"] = self.client._client
        self.client.complete(system="s", messages=[
            {"role": "user", "content": [{"type": "text", "text": text}]}])
        return "ok"

    monkeypatch.setattr("birkin.agent.Agent.run", run)
    summon.summon("doc-analyst", "요약", session.ctx)

    child = argv["client"]
    assert child is not session.client
    assert child.cli_access == "read-only" and child.birkin_mcp is False
    assert session.client.birkin_mcp is True       # parent untouched
    parts = argv["parts"]
    assert parts[parts.index("--sandbox") + 1] == "read-only"
    assert not any("mcp_servers" in part for part in parts)


def test_nested_children_meter_only_their_own_calls(monkeypatch):
    session = _session()
    inner = _ScriptedClient()
    session.ctx.client = subagent_mod._MeteredClient(inner)   # a child's ctx
    seen = {}

    def run(self, text, on_text=None, abort=None):
        seen["base"] = self.client._client
        return "ok"

    monkeypatch.setattr("birkin.agent.Agent.run", run)
    subagent_mod.run_subagent("grandchild", session.ctx)
    assert seen["base"] is inner


def test_guidance_filter_never_touches_user_instructions_or_policy(monkeypatch):
    from birkin import prompts

    _write_agent("clause-checker", _VALID.replace(
        "contract-reviewer", "clause-checker").replace(
        "You review contracts for risky clauses.",
        "- Always remember to cite the clause number.\n"
        "- Use load_skill output only as background."))
    session = _session()
    seen = _capture_run(monkeypatch)

    summon.summon("clause-checker", "검토", session.ctx)

    system = seen["system"]
    assert "- Always remember to cite the clause number." in system
    assert "- Use load_skill output only as background." in system
    assert "remember tool" not in system          # Birkin's own line is gone
    assert system.count(prompts.RESEARCH_EVIDENCE_OPEN) == 1
