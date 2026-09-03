"""Opening a saved conversation from /dash must reach a real slash command."""

from __future__ import annotations

from typing import Any

import pytest

from birkin import dash, slashcommands


def test_load_is_not_a_command_but_sessions_is() -> None:
    # The premise of the bug: "/load <title>" could only ever print
    # "Unknown command /load".
    assert "load" not in slashcommands._REGISTRY
    assert "load" not in slashcommands._ALIASES
    assert "sessions" in slashcommands._REGISTRY


def test_open_session_dispatches_sessions_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched: list[str] = []

    def record(_session: Any, line: str) -> str:
        dispatched.append(line)
        return "continue"

    monkeypatch.setattr(slashcommands, "dispatch", record)

    assert dash._open_session(object(), {"title": "어제 회의"}) is None
    assert dispatched == ["/sessions load 어제 회의"]


def test_open_session_reports_a_failure_instead_of_swallowing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_session: Any, _line: str) -> str:
        raise RuntimeError("transcript is corrupt")

    monkeypatch.setattr(slashcommands, "dispatch", explode)

    error = dash._open_session(object(), {"title": "어제 회의"})

    assert error is not None
    assert "세션을 불러오지 못했습니다" in error
    assert "transcript is corrupt" in error
