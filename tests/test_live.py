"""Live-LLM verification tests.

Skipped by default. To run, install a backend (an ANTHROPIC_API_KEY env var or
the `claude` / `codex` CLI logged in) and:

    BIRKIN_LIVE=1 pytest -m live

Costs should stay tiny (short prompts, Haiku / sonnet / the CLI's own quota).
"""

from __future__ import annotations

import os
import shutil

import pytest

pytestmark = pytest.mark.live

LIVE_ENABLED = os.environ.get("BIRKIN_LIVE") == "1"


def _backend() -> tuple[str, str | None]:
    """Return (provider, model) for the cheapest available backend, or skip."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", "claude-haiku-4-5-20251001"
    if shutil.which("claude"):
        return "claude-cli", "sonnet"
    if shutil.which("codex"):
        return "codex-cli", ""
    pytest.skip("no live backend (need ANTHROPIC_API_KEY or claude/codex CLI)")


@pytest.fixture
def live_session():
    if not LIVE_ENABLED:
        pytest.skip("set BIRKIN_LIVE=1 to run the live suite")
    from birkin import config
    from birkin.runtime import build_session
    provider, model = _backend()
    cfg = config.load_config()
    cfg["provider"] = provider
    if model is not None:
        cfg["model"] = model
    return build_session(cfg)


def test_live_chat_returns_nonempty_reply(live_session):
    reply = live_session.ask("Reply with exactly: OK")
    assert isinstance(reply, str) and len(reply.strip()) > 0


def test_live_chat_with_tool_use_or_useful_reply(live_session, tmp_path):
    """For API providers (anthropic/openai) the agent must actually call a
    tool; for CLI proxies birkin can't observe tool calls so we settle for a
    plausible answer count."""
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
    live_session.ctx.cwd = tmp_path  # birkin tools operate in tmp_path
    reply = live_session.ask(
        "List the files in the current workspace, then state the count as a "
        "single digit. Use your tools to actually inspect.")

    assert reply and any(d in reply for d in "0123456789")
    if live_session.client.provider in ("anthropic", "openai"):
        # native loop -> birkin actually saw a tool call
        assert live_session.agent.last_tools, "no tools were called"
    else:
        # CLI proxy mode: tool execution happens inside the CLI; just sanity-check.
        assert "txt" in reply.lower() or len(reply) > 5


def test_live_subagent_round_trip(live_session, monkeypatch):
    """Only meaningful in native-tool mode; skip in CLI proxy mode."""
    if live_session.client.provider in ("claude-cli", "codex-cli", "local-cli"):
        pytest.skip("subagent loop only runs natively for API providers")
    from birkin import subagent
    out = subagent.run_subagent("Reply with exactly: pong", live_session.ctx,
                                max_turns=4)
    assert isinstance(out, str) and len(out.strip()) > 0
