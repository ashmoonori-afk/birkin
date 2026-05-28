"""Shared test fixtures. Every test runs against an isolated, temporary
BIRKIN_HOME and with provider API keys scrubbed, so the suite never touches the
real ~/.birkin or makes network/API calls."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "bk"
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return home
