from __future__ import annotations

from pathlib import Path

import pytest

from birkin import mcp_server, morpheus


def test_mcp_uses_effective_model_preset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("BIRKIN_MCP_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("BIRKIN_MCP_SCOPE", "full")

    tools = mcp_server._build_tools()

    assert "market_quote" not in tools


def test_mcp_launch_config_carries_effective_model() -> None:
    payload = mcp_server.mcp_config_dict(model="claude-haiku-4-5")
    server = payload["mcpServers"]["birkin"]

    assert server["env"]["BIRKIN_MCP_MODEL"] == "claude-haiku-4-5"
    args = mcp_server.codex_config_args(model="gpt-5.6")
    assert any("BIRKIN_MCP_MODEL" in arg and "gpt-5.6" in arg for arg in args)


@pytest.mark.parametrize(
    ("model", "mcp_model"),
    [
        ("claude-haiku-4-5", "claude-haiku-4-5"),
        ("", "unknown"),
    ],
)
def test_morpheus_mcp_uses_effective_or_neutral_model(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    mcp_model: str,
) -> None:
    captured: dict[str, object] = {}

    def write_config(path: Path, **kwargs: object) -> Path:
        captured.update(kwargs)
        path.write_text("{}", encoding="utf-8")
        return path

    class FakeClaudeSession:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def ask(self, _task: str) -> str:
            return "done"

        def close(self) -> None:
            pass

    monkeypatch.setattr(mcp_server, "write_mcp_config", write_config)
    from birkin import claude_session
    monkeypatch.setattr(
        claude_session,
        "ClaudeStreamSession",
        FakeClaudeSession,
    )

    result = morpheus._run_claude_morpheus(
        {"model": model},
        "review",
        True,
        0,
    )

    assert result == 0
    assert captured["model"] == mcp_model
