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
