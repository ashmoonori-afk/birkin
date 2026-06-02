import os

import pytest

from birkin import proc


def test_shell_argv_wraps_command_string():
    argv = proc.shell_argv("echo hi")
    assert argv[-1] == "echo hi"
    assert argv[0] in ("bash", "cmd")
    if os.name == "nt":
        assert argv == ["cmd", "/c", "echo hi"]
    else:
        assert argv == ["bash", "-lc", "echo hi"]


def test_cli_argv_keeps_parts_discrete():
    argv = proc.cli_argv(["claude", "-p", "--model", "sonnet"])
    assert "claude" in argv and "--model" in argv and "sonnet" in argv
    if os.name == "nt":
        assert argv[:2] == ["cmd", "/c"]
    else:
        assert argv == ["claude", "-p", "--model", "sonnet"]


def test_cli_argv_rejects_windows_shell_metachars(monkeypatch):
    # On Windows, cmd /c re-parses metacharacters inside each arg, so a smuggled
    # `& calc` would chain a second command — cli_argv must reject it.
    monkeypatch.setattr(proc.os, "name", "nt")
    for bad in ("foo & calc", "a|b", "x>out", "y<in", "z^a"):
        with pytest.raises(ValueError):
            proc.cli_argv(["claude", "mcp", "add", "srv", bad])
    # The program name itself is trusted and not scanned; clean args pass.
    assert proc.cli_argv(["claude", "mcp", "list"])[:2] == ["cmd", "/c"]


def test_cli_argv_allows_metachars_on_posix(monkeypatch):
    # POSIX uses a discrete argv with no shell, so metachars are literal data.
    monkeypatch.setattr(proc.os, "name", "posix")
    assert proc.cli_argv(["claude", "x & y"]) == ["claude", "x & y"]


# -- claude_child_env: disable the ECC interactive SessionStart hook -------
#
# birkin spawns `claude` as an engine and injects its OWN persona/memory/skills.
# The ECC plugin's SessionStart hook injects an unrelated "Previous session
# summary" which the model then surfaces on the first turn — leaking a session
# dump into gateway/Telegram replies. claude_child_env disables it per-subprocess.

def _disabled_ids(env: dict) -> list[str]:
    return [h.strip() for h in env.get("ECC_DISABLED_HOOKS", "").split(",")
            if h.strip()]


def test_claude_child_env_disables_session_start_hook():
    assert "session:start" in _disabled_ids(proc.claude_child_env())


def test_claude_child_env_preserves_existing_disabled_hooks(monkeypatch):
    monkeypatch.setenv("ECC_DISABLED_HOOKS", "foo:bar")
    ids = _disabled_ids(proc.claude_child_env())
    assert "foo:bar" in ids and "session:start" in ids


def test_claude_child_env_is_idempotent(monkeypatch):
    """Already-disabled session:start must not be duplicated."""
    monkeypatch.setenv("ECC_DISABLED_HOOKS", "session:start")
    assert _disabled_ids(proc.claude_child_env()).count("session:start") == 1


def test_claude_child_env_inherits_parent_env(monkeypatch):
    monkeypatch.setenv("BIRKIN_TEST_SENTINEL", "xyz")
    assert proc.claude_child_env().get("BIRKIN_TEST_SENTINEL") == "xyz"
