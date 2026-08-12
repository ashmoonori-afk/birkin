from __future__ import annotations

import pytest

from birkin import cli
from birkin.moirai import cli as moirai_cli


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
