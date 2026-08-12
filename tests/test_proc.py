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
    assert "--model" in argv and "sonnet" in argv
    if os.name == "nt":
        assert argv[:2] == ["cmd", "/c"]
        assert os.path.basename(argv[2]).lower() in ("claude", "claude.cmd")
    else:
        assert argv == ["claude", "-p", "--model", "sonnet"]


@pytest.mark.skipif(os.name != "nt", reason="Windows npm shim lookup")
def test_cli_argv_falls_back_to_user_npm_shim(monkeypatch, tmp_path):
    # Simulating "nt" on POSIX is not enough here: pathlib.Path picks its
    # flavour from os.name at construction time, so cli_argv's Path(APPDATA)
    # would raise NotImplementedError, and pytest's own failure reporting
    # (which also builds a Path) would then abort the whole session with an
    # INTERNALERROR instead of reporting one failed test.
    appdata = tmp_path / "AppData" / "Roaming"
    npm = appdata / "npm"
    npm.mkdir(parents=True)
    shim = npm / "claude.cmd"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setattr(proc.os, "name", "nt")
    monkeypatch.setenv("APPDATA", str(appdata))

    argv = proc.cli_argv(["claude", "--version"])

    assert argv == ["cmd", "/c", str(shim), "--version"]


def test_cli_argv_rejects_windows_shell_metachars(monkeypatch):
    # On Windows, cmd /c re-parses metacharacters inside each arg, so a smuggled
    # `& calc` would chain a second command — cli_argv must reject it.
    monkeypatch.setattr(proc.os, "name", "nt")
    # Keep the simulated branch off pathlib: with APPDATA set, cli_argv builds a
    # Path, which cannot be a WindowsPath on POSIX.
    monkeypatch.delenv("APPDATA", raising=False)
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
