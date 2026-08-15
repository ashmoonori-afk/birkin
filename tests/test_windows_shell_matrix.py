"""Native Windows acceptance matrix for managed free-form shell commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from birkin.proc import ShellCommand, run_shell_command, shell_env

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="native Windows cmd.exe acceptance",
)


def _command(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts)


def _source(*lines: str) -> str:
    return "\n".join((*lines, ""))


def _run(
    command: str,
    cwd: Path,
    *,
    environment: dict[str, str] | None = None,
    stdin: str | None = None,
    timeout: int = 15,
) -> subprocess.CompletedProcess[str]:
    return run_shell_command(
        ShellCommand(
            command=command,
            cwd=cwd,
            timeout=timeout,
            environment=environment or shell_env(),
            stdin=stdin,
        )
    )


def test_native_cmd_builtins_and_unicode_output(tmp_path: Path) -> None:
    workspace = tmp_path / "한글 builtins"
    _ = workspace.mkdir()
    marker = workspace / "표시 파일.txt"
    _ = marker.write_text("ok", encoding="utf-8")
    hijack_marker = workspace / "chcp-hijacked.txt"
    _ = (workspace / "chcp.cmd").write_text(
        "@echo off\r\n"
        + f"echo hijacked>\"{hijack_marker}\"\r\n"
        + "exit /b 0\r\n",
        encoding="utf-8",
    )
    hijack_marker = workspace / "chcp-hijacked.txt"
    _ = (workspace / "chcp.cmd").write_text(
        "@echo off\r\n"
        + f"echo hijacked>\"{hijack_marker}\"\r\n"
        + "exit /b 0\r\n",
        encoding="utf-8",
    )
    environment = shell_env()
    environment["BIRKIN_MATRIX_VALUE"] = "inherited-ok"
    cases = (
        ("echo 한글✓", "한글✓"),
        ("cd", str(workspace)),
        ("dir /b", marker.name),
        ("set BIRKIN_MATRIX_VALUE", "BIRKIN_MATRIX_VALUE=inherited-ok"),
        ("where python", "python.exe"),
    )

    for command, expected in cases:
        result = _run(command, workspace, environment=environment)
        assert result.returncode == 0, (command, result.stderr)
        assert expected.casefold() in result.stdout.casefold(), (
            command,
            result.stdout,
        )
        assert not hijack_marker.exists()
        assert not hijack_marker.exists()


def test_external_runtime_and_wrapper_matrix(tmp_path: Path) -> None:
    commands = (
        (_command(["python", "-c", "print('python-ok')"]), "python-ok"),
        ("git --version", "git version"),
        (_command(["node", "-e", "console.log('node-ok')"]), "node-ok"),
        ("npm --version", "."),
        ("npm.cmd --version", "."),
        ("bun --version", "."),
        ("bun.exe --version", "."),
        ("bunx --version", "."),
    )

    for command, expected in commands:
        result = _run(command, tmp_path)
        assert result.returncode == 0, (command, result.stderr)
        assert expected in result.stdout, (command, result.stdout)


def test_operators_redirection_stdin_and_quoting(tmp_path: Path) -> None:
    source = tmp_path / "input 한글.txt"
    output = tmp_path / "output 한글.txt"
    _ = source.write_text("stdin-value\n", encoding="utf-8")
    quoted_source = _command([str(source)])
    quoted_output = _command([str(output)])
    command = (
        f"type {quoted_source} | findstr stdin > {quoted_output} && "
        f"type {quoted_source} >> {quoted_output} && "
        f"findstr stdin < {quoted_source} >> {quoted_output} && "
        f"(cmd /d /c exit 0) && (echo and-ok) >> {quoted_output} && "
        f"(cmd /d /c exit 7) || (echo or-ok) >> {quoted_output}"
    )

    result = _run(command, tmp_path)

    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8").splitlines() == [
        "stdin-value",
        "stdin-value",
        "stdin-value",
        "and-ok",
        "or-ok",
    ]


def test_streams_exit_code_and_empty_output(tmp_path: Path) -> None:
    command = _command(
        [
            sys.executable,
            "-c",
            (
                "import sys; print('stdout-ok'); "
                "print('stderr-ok', file=sys.stderr); raise SystemExit(23)"
            ),
        ]
    )

    result = _run(command, tmp_path)
    empty = _run("cmd /d /c exit 0", tmp_path)

    assert result.returncode == 23
    assert result.stdout == "stdout-ok\n"
    assert result.stderr == "stderr-ok\n"
    assert empty.returncode == 0
    assert empty.stdout == ""
    assert empty.stderr == ""


def test_environment_temp_and_cwd_boundaries(tmp_path: Path) -> None:
    workspace = tmp_path / "cwd 한글"
    child = workspace / "child"
    temp = tmp_path / "writable temp"
    _ = workspace.mkdir()
    _ = child.mkdir()
    _ = temp.mkdir()
    environment = shell_env()
    environment.update(
        {
            "BIRKIN_INHERITED": "inherited",
            "BIRKIN_OVERRIDE": "overridden",
            "TEMP": str(temp),
            "TMP": str(temp),
        }
    )
    probe = workspace / "environment probe.py"
    _ = probe.write_text(
        _source(
            "import os",
            "from pathlib import Path",
            "assert os.environ['BIRKIN_INHERITED'] == 'inherited'",
            "assert os.environ['BIRKIN_OVERRIDE'] == 'overridden'",
            "assert os.environ['TEMP'] == os.environ['TMP']",
            "probe = Path(os.environ['TEMP']) / 'writable.txt'",
            "probe.write_text('ok', encoding='utf-8')",
            "probe.unlink()",
            "print(Path.cwd())",
        ),
        encoding="utf-8",
    )
    parent_cwd = Path.cwd()

    result = _run(
        _command([sys.executable, str(probe)]),
        workspace,
        environment=environment,
    )
    changed = _run("cd child && cd", workspace, environment=environment)

    assert result.returncode == 0, result.stderr
    assert str(workspace) in result.stdout
    assert changed.returncode == 0
    assert str(child) in changed.stdout
    assert Path.cwd() == parent_cwd


def test_long_command_survives_bootstrap_transport(tmp_path: Path) -> None:
    payload = "long-transport-" + ("x" * 6000)
    command = _command(
        [sys.executable, "-c", f"print({payload!r})"]
    )

    result = _run(command, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == payload
    assert len(result.stdout) > 6000


def test_stdin_payload_is_forwarded_without_requoting(tmp_path: Path) -> None:
    command = _command(
        [
            sys.executable,
            "-c",
            "import sys; print(sys.stdin.read())",
        ]
    )

    result = _run(command, tmp_path, stdin="한글 stdin ✓")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "한글 stdin ✓\n"
