"""A workflow's outcome is honest and readable, not a status enum.

`status == "completed"` only means `main(m)` returned. These tests pin the
contract on top of it: the engine's summary carries a `completion` (complete,
partial, failed) and a failure count, lane and pipeline exceptions are
recorded instead of vanishing into `None`, and `outcome.render` turns a run
into the Korean text every surface shows -- status line first, the result
itself with real newlines, then the run id.
"""

from __future__ import annotations

import json

import pytest

from birkin import moirai
from birkin.moirai import cli as moirai_cli
from birkin.moirai import journal, outcome


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _run(tmp_path, body: str, spawn) -> dict:
    path = tmp_path / "wf.py"
    path.write_text(body, encoding="utf-8")
    return moirai.run_script(moirai.load_script(path), cfg={}, spawn=spawn)


TWO_AGENTS = '''
meta = {"name": "two", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    first = m.agent("first", role="w")
    second = m.agent("second", role="w")
    return f"{first} / {second}"
'''


def _fails(*prompts):
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        if prompt in prompts:
            return "[provider-error] codex: auth expired"
        return prompt.upper()
    return spawn


# ---------------- the engine's completion ---------------------------------

def test_one_failed_agent_of_two_is_partial(tmp_path):
    out = _run(tmp_path, TWO_AGENTS, _fails("second"))
    assert out["status"] == "completed"
    assert out["completion"] == "partial"
    assert out["failures"] == 1
    assert moirai_cli._outcome_exit_code(out) == 0


def test_every_agent_failing_is_failed(tmp_path):
    out = _run(tmp_path, TWO_AGENTS, _fails("first", "second"))
    assert out["status"] == "completed"
    assert out["completion"] == "failed"
    assert out["failures"] == 2
    assert moirai_cli._outcome_exit_code(out) == 1


def test_a_clean_run_is_complete_with_no_failures(tmp_path):
    out = _run(tmp_path, TWO_AGENTS, _fails())
    assert out["completion"] == "complete"
    assert out["failures"] == 0
    assert moirai_cli._outcome_exit_code(out) == 0


def test_a_script_returning_an_error_is_failed(tmp_path):
    out = _run(tmp_path, '''
meta = {"name": "err", "roles": {}}

def main(m):
    return {"error": "x"}
''', _fails())
    assert out["completion"] == "failed"
    assert moirai_cli._outcome_exit_code(out) == 1


def test_a_declared_completion_wins_over_the_failure_rows(tmp_path):
    out = _run(tmp_path, '''
meta = {"name": "declared", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    m.agent("first", role="w")
    return {"answer": "fallback worked", "completion": "complete"}
''', _fails("first"))
    assert out["failures"] == 1
    assert out["completion"] == "complete"


def test_a_raising_lane_is_recorded_not_swallowed(tmp_path):
    out = _run(tmp_path, '''
meta = {"name": "lanes", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return m.parallel([lambda: 1 / 0, lambda: m.agent("ok", role="w")])
''', _fails())
    assert out["result"] == [None, "OK"]
    assert out["completion"] == "partial"
    run = journal.get_run(out["run_id"])
    assert run is not None
    failures = json.loads(run["result_json"])["failures"]
    assert [f["reason"] for f in failures] == ["script-exception"]
    assert failures[0]["label"] == "lane:0"
    assert "ZeroDivisionError" in failures[0]["error"]
    assert "Traceback (most recent call last)" in failures[0]["traceback"]


def test_a_raising_pipeline_stage_is_recorded(tmp_path):
    out = _run(tmp_path, '''
meta = {"name": "pipe", "roles": {"w": {"default": "codex:x"}}}

def boom(prev, item, index):
    raise ValueError("stage bug")

def main(m):
    return m.pipeline(["x"], lambda item, *_: m.agent(item, role="w"), boom)
''', _fails())
    assert out["result"] == [None]
    assert out["failures"] == 1
    assert out["completion"] == "partial"


def test_a_script_exception_alone_is_not_an_agent_failure(tmp_path):
    """Two agents succeeded; a thunk bug makes the run partial, not failed."""
    out = _run(tmp_path, '''
meta = {"name": "mixed", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    m.agent("a", role="w")
    return m.parallel([lambda: m.agent("b", role="w"), lambda: {}["missing"]])
''', _fails())
    assert out["completion"] == "partial"


@pytest.mark.parametrize("status,expected", [
    ("aborted", "aborted"),
    ("waiting_input", "waiting"),
    ("error", "failed"),
])
def test_completion_follows_a_non_completed_status(status, expected):
    out = {"status": status, "result": {"completion": "complete"}}
    assert outcome.completion(out) == expected
    assert outcome.exit_code(out) == 1


# ---------------- the rendered text ---------------------------------------

def _out(result, **extra):
    return {"run_id": "20260926-000000-abcd", "status": "completed",
            "result": result, "agents": 3, "cache_hits": 0, "tokens": 10,
            "seconds": 12.3, **extra}


def test_render_leads_with_status_and_ends_with_the_run_id():
    text = outcome.render(_out("VERDICT: 완료 — 보고서\n\n본문: 매출 12% 증가"),
                          name="hard-task")
    lines = text.splitlines()
    assert lines[0].startswith("✅ 워크플로우 완료")
    assert "(hard-task)" in lines[0] and "에이전트 3명" in lines[0]
    assert "VERDICT: 완료 — 보고서\n\n본문: 매출 12% 증가" in text
    assert "\\n" not in text
    assert lines[-1] == "실행 기록: 20260926-000000-abcd"
    assert "birkin moirai status" not in text


def test_render_names_the_failures_in_the_status_line():
    text = outcome.render(_out("r", completion="partial", failures=2))
    assert text.splitlines()[0].startswith("⚠️ 워크플로우 일부 완료")
    assert "실패 2건" in text.splitlines()[0]


def test_a_failed_completion_leads_with_a_failure_mark():
    text = outcome.render(_out({"answer": "VERDICT: 미완료", "completion": "failed"}))
    assert text.splitlines()[0].startswith("❌ 워크플로우 실패")
    assert "VERDICT: 미완료" in text


def test_an_error_result_explains_itself_in_korean():
    text = outcome.render(_out({"error": "tree rejected: no leaves"}))
    assert text.splitlines()[0].startswith("❌")
    assert outcome.NO_RESULT in text


def test_a_waiting_run_says_what_it_waits_for():
    text = outcome.render({"run_id": "r", "status": "waiting_input",
                           "result": {"action_id": "abc"}})
    assert text.splitlines()[0].startswith("⏸️ 워크플로우 입력 대기")
    assert outcome.WAITING in text
    assert "action_id" not in text


def test_an_unknown_structure_is_a_labelled_secondary_detail():
    text = outcome.render(_out({"draft": "초안", "critiques": []}))
    assert "세부 결과:" in text
    assert "초안" in text


def test_a_limit_cuts_only_the_body_and_says_so():
    text = outcome.render(_out("가" * 5000), name="hard-task", limit=1900)
    assert len(text) <= 1900
    lines = text.splitlines()
    assert lines[0].startswith("✅ 워크플로우 완료 (hard-task)")
    assert lines[-1] == "실행 기록: 20260926-000000-abcd"
    assert outcome.TRUNCATED in text


def test_research_sections_travel_with_the_answer():
    text = outcome.render(_out({
        "answer": "근거 있는 답변", "completion": "partial",
        "reasons": ["발행일 미확인"],
        "verification_basis": "인용 실재는 코드 확인",
        "claim_ledger": [{"claim": "추가 확인", "status": "unresolved"}],
    }))
    assert text.splitlines()[0].startswith("⚠️ 워크플로우 일부 완료")
    assert "미확정 또는 반박된 항목:\n- 추가 확인" in text
    assert "남은 제약:\n- 발행일 미확인" in text
    assert "검증 기준: 인용 실재는 코드 확인" in text


def test_a_raising_lane_without_agents_is_partial_not_failed(tmp_path):
    """No agent died: a thunk bug costs the run its 'complete', not more."""
    out = _run(tmp_path, '''
meta = {"name": "no-agents", "roles": {}}

def main(m):
    return m.parallel([lambda: "first", lambda: 1 / 0])
''', _fails())
    assert out["completion"] == "partial"
    assert moirai_cli._outcome_exit_code(out) == 0
