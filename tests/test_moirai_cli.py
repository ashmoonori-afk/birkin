from __future__ import annotations

import pytest
from typing import Any, cast

from birkin import cli
from birkin.moirai import cli as moirai_cli


def test_help_describes_positional_status_and_resume_run_ids() -> None:
    parser = cli.build_parser()
    subparsers = next(
        action for action in parser._actions
        if getattr(action, "choices", None)
    )
    moirai_parser = cast(Any, subparsers).choices["moirai"]
    positional = next(
        action for action in moirai_parser._actions if action.dest == "script"
    )

    assert "workflow file or name" in positional.help
    assert "run id" in positional.help
    assert "status / resume" in positional.help


def test_status_accepts_documented_positional_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def missing_run(run_id: str) -> None:
        seen.append(run_id)

    monkeypatch.setattr(moirai_cli.journal, "get_run", missing_run)

    assert cli.main(["moirai", "status", "run-123"]) == 1
    assert seen == ["run-123"]


def test_resume_accepts_documented_positional_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def missing_run(run_id: str) -> None:
        seen.append(run_id)

    monkeypatch.setattr(moirai_cli.journal, "get_run", missing_run)

    assert cli.main(["moirai", "resume", "run-456"]) == 1
    assert seen == ["run-456"]


def test_quiet_run_prints_only_the_rendered_outcome(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An approved worker keeps the first 2000 chars of stdout as its receipt,
    so --quiet must lead with the outcome: no plan table, no agent trace."""
    import json

    from birkin.moirai import bindings, engine

    monkeypatch.setenv("NO_COLOR", "1")

    def spawn(prompt: str, binding: Any, opts: Any, cfg: Any, *,
              timeout: float = 900.0, abort: Any = None) -> str:
        if binding.role == "planner":
            return json.dumps({"items": ["정리"]})
        if binding.role == "decomposer":
            return json.dumps({"items": ["정리 A", "정리 B"]})
        return json.dumps({"result": "끝\n다음 줄", "followups": []},
                          ensure_ascii=False)

    monkeypatch.setattr(engine, "_default_spawn", spawn)
    monkeypatch.setattr(bindings, "validate", lambda *_a, **_k: None)

    code = cli.main([
        "moirai", "run", "hard-task", "--args", '{"task": "t"}',
        "--defaults", "--quiet",
    ])

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("✅ 워크플로우 완료 (hard-task)")
    assert "VERDICT: 완료" in out[:2000]
    assert "끝\n다음 줄" in out            # real newlines, not JSON-escaped
    assert "\\n" not in out
    assert "planner" not in out and "decomposer" not in out   # plan table
    assert "[step-" not in out and "subagent" not in out       # agent trace
    assert "birkin moirai status" not in out


def test_run_with_invalid_args_json_fails_before_running(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        moirai_cli, "run_script",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("ran")))

    code = cli.main([
        "moirai", "run", "hard-task", "--args", "[1, 2]",
        "--defaults", "--quiet",
    ])

    assert code == 1
    assert "--args는 JSON 객체여야 합니다" in capsys.readouterr().out
