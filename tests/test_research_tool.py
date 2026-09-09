from __future__ import annotations

from pathlib import Path
from threading import Event

from birkin.tools import ToolContext, build_registry
from birkin.tools import research
from birkin.moirai import cli as moirai_cli


def test_research_run_uses_only_bundled_workflow_and_returns_readable_result(
    tmp_path: Path, monkeypatch,
) -> None:
    captured = {}
    monkeypatch.setattr(research.moirai_cli, "resolve_script_path", lambda name: Path(name))
    class Script:
        roles = {"researcher": {"default": "claude:sonnet", "tools": "read-only"}}

    script = Script()
    monkeypatch.setattr(research, "load_script", lambda path: script)

    def run(script, **kwargs):
        captured.update(script=script, **kwargs)
        return {
            "run_id": "research-1",
            "status": "completed",
            "result": {
                "answer": "검증된 답변 [S1](https://example.com/source)",
                "completion": "partial",
                "reasons": ["발행일 미확인"],
                "verification_basis": "인용 실재는 코드 확인, 의미는 모델 감사",
                "claim_ledger": [{"claim": "추가 확인 필요", "status": "unresolved"}],
            },
        }

    monkeypatch.setattr(research, "run_script", run)
    events = []
    abort = Event()
    ctx = ToolContext(
        cfg={"provider": "codex-cli", "model": "configured-model"}, client=None, cwd=tmp_path,
        emit=lambda event, payload: events.append((event, payload)), abort=abort,
    )

    result = build_registry(ctx, include={"research"}).execute(
        "research_run",
        {"question": " 무엇을 확인할까요? ", "source_urls": ["https://example.com/source"]},
    )

    assert not result.is_error
    assert "검증된 답변" in result.content and "추가 확인 필요" in result.content
    assert "검증 기준: 인용 실재는 코드 확인, 의미는 모델 감사" in result.content
    assert "research-1" in result.content and not result.content.lstrip().startswith("{")
    assert captured["script"] is script
    assert captured["cfg"] == ctx.cfg
    assert captured["args"] == {
        "question": "무엇을 확인할까요?", "source_urls": ["https://example.com/source"],
        "_workspace": str(tmp_path.resolve()),
    }
    binding = captured["bindings_map"]["researcher"]
    assert binding.provider == "codex" and binding.model == "configured-model"
    assert captured["on_event"] is ctx.emit and captured["abort"] is abort


def test_research_run_rejects_paths_and_non_http_sources(tmp_path: Path) -> None:
    tool = research.tools()[0]
    assert set(tool.input_schema["properties"]) == {"question", "source_urls"}
    assert tool.input_schema["additionalProperties"] is False
    result = tool.fn(
        {"question": "조사", "source_urls": ["C:/private/report.txt"]},
        ToolContext(cfg={}, client=None, cwd=tmp_path),
    )
    assert result.is_error
    malformed = tool.fn(
        {"question": "조사", "source_urls": ["https://[invalid"]},
        ToolContext(cfg={}, client=None, cwd=tmp_path),
    )
    assert malformed.is_error


def test_research_run_honors_main_turn_abort_before_start(tmp_path: Path, monkeypatch) -> None:
    abort = Event()
    abort.set()
    monkeypatch.setattr(
        research, "run_script",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("started")),
    )
    result = build_registry(ToolContext(
        cfg={}, client=None, cwd=tmp_path, abort=abort,
    ), include={"research"}).execute("research_run", {"question": "조사"})
    assert result.is_error
    assert "시작되기 전에 중단" in result.content


def test_research_run_marks_failed_completion_as_error(tmp_path: Path, monkeypatch) -> None:
    class Script:
        roles = {}

    monkeypatch.setattr(research.moirai_cli, "resolve_script_path", lambda name: Path(name))
    monkeypatch.setattr(research, "load_script", lambda path: Script())
    monkeypatch.setattr(research, "run_script", lambda *args, **kwargs: {
        "run_id": "research-failed", "status": "completed",
        "result": {"completion": "failed", "answer": "", "reasons": ["연결 실패"]},
    })
    result = research.tools()[0].fn(
        {"question": "조사"}, ToolContext(cfg={}, client=None, cwd=tmp_path))
    assert result.is_error
    assert "완료하지 못함" in result.content and "연결 실패" in result.content


def test_research_run_prioritizes_outer_abort_over_partial_result(tmp_path: Path, monkeypatch) -> None:
    class Script:
        roles = {}

    monkeypatch.setattr(research.moirai_cli, "resolve_script_path", lambda name: Path(name))
    monkeypatch.setattr(research, "load_script", lambda path: Script())
    monkeypatch.setattr(research, "run_script", lambda *args, **kwargs: {
        "run_id": "aborted", "status": "aborted",
        "result": {"completion": "partial", "answer": "일부 결과"},
    })
    result = research.tools()[0].fn(
        {"question": "조사"}, ToolContext(cfg={}, client=None, cwd=tmp_path))
    assert result.is_error and "조사 상태: 중단" in result.content


def test_research_run_treats_default_model_as_provider_default(tmp_path: Path, monkeypatch) -> None:
    class Script:
        roles = {"researcher": {"default": "claude:sonnet"}}

    captured = {}
    monkeypatch.setattr(research.moirai_cli, "resolve_script_path", lambda name: Path(name))
    monkeypatch.setattr(research, "load_script", lambda path: Script())

    def run(*args, **kwargs):
        captured.update(kwargs)
        return {"run_id": "r", "status": "completed", "result": {
            "completion": "complete", "answer": "답변",
        }}

    monkeypatch.setattr(research, "run_script", run)
    result = research.tools()[0].fn(
        {"question": "조사"},
        ToolContext(cfg={"provider": "codex-cli", "model": "default"}, client=None, cwd=tmp_path),
    )
    assert not result.is_error
    assert captured["bindings_map"]["researcher"].spec == "codex:"


def test_research_cli_prints_the_complete_answer(capsys) -> None:
    answer = "근거 있는 답변\n" + "본문" * 800
    moirai_cli._print_outcome({
        "run_id": "research-1", "status": "completed", "agents": 3,
        "cache_hits": 0, "seconds": 1.0, "tokens": 100,
        "result": {
            "completion": "partial", "answer": answer,
            "reasons": ["발행일 미확인"],
            "verification_basis": "인용 실재는 코드 확인, 의미는 모델 감사",
            "claim_ledger": [{"claim": "추가 확인", "status": "unresolved"}],
        },
    })

    output = capsys.readouterr().out
    assert answer in output
    assert "연구 상태: 일부 완료" in output
    assert "미확정 또는 반박된 항목:\n- 추가 확인" in output
    assert "남은 제약:\n- 발행일 미확인" in output
    assert "검증 기준: 인용 실재는 코드 확인, 의미는 모델 감사" in output


def test_research_cli_failed_completion_returns_failure() -> None:
    assert moirai_cli._outcome_exit_code({
        "status": "completed", "result": {"completion": "failed"},
    }) == 1


def test_research_cli_reports_aborted_outer_run(capsys) -> None:
    outcome = {
        "run_id": "research-aborted", "status": "aborted", "agents": 1,
        "cache_hits": 0, "seconds": 1.0, "tokens": 1,
        "result": {"completion": "partial", "answer": "확인 중 중단됨"},
    }
    moirai_cli._print_outcome(outcome)
    assert "연구 상태: 중단" in capsys.readouterr().out
    assert moirai_cli._outcome_exit_code(outcome) == 1
