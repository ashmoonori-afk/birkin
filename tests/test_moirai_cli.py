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
