import os

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
