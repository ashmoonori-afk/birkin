"""Native macOS acceptance for Birkin's managed shell contract."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from birkin.tools import ToolContext, ToolResult
from birkin.tools import shell as shell_mod

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="native macOS shell acceptance",
)


def _command(parts: list[str]) -> str:
    return shlex.join(parts)


# Cold process startup on a loaded CI runner routinely outruns a 10s budget -
# a slow host, not a hung command. Callers that assert on timeout behaviour
# itself pass their own short budget, so widening this default weakens nothing.
def _run(
    command: str,
    cwd: Path,
    timeout: int = 60,
    *,
    cfg: dict[str, object] | None = None,
) -> ToolResult:
    tool = next(tool for tool in shell_mod.tools() if tool.name == "run_shell")
    context = ToolContext(cfg=cfg or {}, client=None, cwd=cwd)
    return tool.fn({"command": command, "timeout": timeout}, context)


def _process_running(pid: int) -> bool:
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def test_nonlogin_shell_operators_glob_and_unicode_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "isolated home"
    home.mkdir()
    profile_marker = tmp_path / "profile-loaded"
    _ = (home / ".bash_profile").write_text(
        f"touch {shlex.quote(str(profile_marker))}\nexit 99\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    workspace = tmp_path / "한글 shell workspace"
    workspace.mkdir()
    output = workspace / "quoted output.txt"
    command = (
        f"printf 'alpha\\n' > {shlex.quote(str(output))} && "
        f"printf 'beta\\n' >> {shlex.quote(str(output))} && "
        f"cat < {shlex.quote(str(output))} | grep beta && "
        "printf 'and-ok\\n' && "
        "(false || printf 'or-ok\\n') && "
        "printf 'glob:%s\\n' *.txt"
    )

    result = _run(command, workspace)

    assert result.is_error is False, result.content
    assert "beta" in result.content
    assert "and-ok" in result.content
    assert "or-ok" in result.content
    assert "glob:quoted output.txt" in result.content
    assert output.read_text(encoding="utf-8") == "alpha\nbeta\n"
    assert not profile_marker.exists()


def test_shell_runtime_and_executable_smokes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    executable = tmp_path / "executable smoke"
    _ = executable.write_text(
        "#!/bin/sh\nprintf 'executable-ok\\n'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    commands = [
        "/bin/bash --version",
        "/bin/zsh --version",
        _command([sys.executable, "--version"]),
        "git --version",
        "node --version",
        "npm --version",
        "bun --version",
        "bunx --version",
        _command([str(executable)]),
    ]

    for command in commands:
        result = _run(command, tmp_path)
        assert result.is_error is False, f"{command}: {result.content}"


def test_streams_environment_cwd_and_temp_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "cwd with spaces"
    workspace.mkdir()
    temp_dirs = {
        name: tmp_path / name.lower()
        for name in ("TMPDIR", "TEMP", "TMP")
    }
    for name, path in temp_dirs.items():
        path.mkdir()
        monkeypatch.setenv(name, str(path))
    monkeypatch.setenv("BIRKIN_MACOS_SENTINEL", "inherited-ok")
    script = workspace / "probe.py"
    _ = script.write_text(
        "import json, os, sys\n"
        + "from pathlib import Path\n"
        + "for name in ('TMPDIR', 'TEMP', 'TMP'):\n"
        + "    root = Path(os.environ[name])\n"
        + "    probe = root / f'{name.lower()}-probe'\n"
        + "    probe.write_text('ok', encoding='utf-8')\n"
        + "    probe.unlink()\n"
        + "print(json.dumps({\n"
        + "    'cwd': str(Path.cwd()),\n"
        + "    'sentinel': os.environ['BIRKIN_MACOS_SENTINEL'],\n"
        + "    'temps': {name: os.environ[name]\n"
        + "              for name in ('TMPDIR', 'TEMP', 'TMP')},\n"
        + "}, ensure_ascii=False))\n"
        + "print('stderr-한글', file=sys.stderr)\n"
        + "raise SystemExit(7)\n",
        encoding="utf-8",
    )

    result = _run(
        _command([sys.executable, str(script)]),
        workspace,
        cfg={
            "shell": {
                "env_passthrough": ["BIRKIN_MACOS_SENTINEL"],
            },
        },
    )

    assert isinstance(result.content, str)
    stdout, stderr = result.content.split("\n[stderr]\n", 1)
    value = cast(object, json.loads(stdout.partition("\n")[2]))
    assert isinstance(value, dict)
    payload = cast(dict[str, object], value)
    assert result.is_error is True
    assert payload["cwd"] == str(workspace)
    assert payload["sentinel"] == "inherited-ok"
    assert payload["temps"] == {
        name: str(path) for name, path in temp_dirs.items()
    }
    assert "stderr-한글" in stderr
    assert "[exit 7]" in result.content


def test_timeout_kills_background_descendant_after_shell_exits(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "background.pid"
    parent = tmp_path / "exit-parent.py"
    _ = parent.write_text(
        "import subprocess, sys\n"
        + "from pathlib import Path\n"
        + "child = subprocess.Popen([\n"
        + "    sys.executable, '-c', 'import time; time.sleep(30)'\n"
        + "])\n"
        + f"Path({str(pid_file)!r}).write_text(str(child.pid), encoding='utf-8')\n",
        encoding="utf-8",
    )

    result = _run(_command([sys.executable, str(parent)]), tmp_path, timeout=1)
    child_pid = int(pid_file.read_text(encoding="utf-8"))

    assert result.is_error is True
    assert isinstance(result.content, str)
    assert "timed out" in result.content.lower()
    assert _process_running(child_pid) is False


def _write_interrupt_driver(tmp_path: Path) -> tuple[Path, Path]:
    """Write a driver that interrupts its own managed shell.

    The driver installs Python's default SIGINT handler before running. A
    process launched in the background inherits SIGINT as ignored, and CPython
    keeps that inherited ignore, so without this the driver would assert on its
    launcher's signal disposition instead of on the shell contract.
    """
    pid_file = tmp_path / "interrupt-child.pid"
    shell_command = (
        f"{_command([sys.executable, '-c', 'import time; time.sleep(30)'])} & "
        "child=$!; "
        f"printf '%s' \"$child\" > {shlex.quote(str(pid_file))}; "
        'kill -INT "$PPID"; wait "$child"'
    )
    driver = tmp_path / "interrupt-driver.py"
    _ = driver.write_text(
        "import signal\n"
        + "from birkin.proc import ShellCommand, run_shell_command, shell_env\n"
        + "from pathlib import Path\n"
        + "signal.signal(signal.SIGINT, signal.default_int_handler)\n"
        + "try:\n"
        + "    run_shell_command(ShellCommand(\n"
        + f"        command={shell_command!r},\n"
        + f"        cwd=Path({str(tmp_path)!r}),\n"
        + "        timeout=30,\n"
        + "        environment=shell_env(),\n"
        + "    ))\n"
        + "except KeyboardInterrupt:\n"
        + "    print('interrupt-cleaned')\n"
        + "else:\n"
        + "    raise SystemExit('expected KeyboardInterrupt')\n",
        encoding="utf-8",
    )
    return driver, pid_file


def test_interrupt_kills_real_shell_process_group(tmp_path: Path) -> None:
    driver, pid_file = _write_interrupt_driver(tmp_path)

    result = subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    child_pid = int(pid_file.read_text(encoding="utf-8"))

    assert result.returncode == 0, result.stderr
    assert "interrupt-cleaned" in result.stdout
    assert _process_running(child_pid) is False


def test_interrupt_cleanup_survives_a_launcher_that_ignores_sigint(
    tmp_path: Path,
) -> None:
    """Given a launcher that ignores SIGINT, as every background shell job does,
    When the managed shell is interrupted, Then the process group is still
    killed and the interrupt is still observed."""
    driver, pid_file = _write_interrupt_driver(tmp_path)
    launcher = (
        "import os, signal, sys\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        f"os.execv({sys.executable!r}, [{sys.executable!r}, {str(driver)!r}])\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", launcher],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    child_pid = int(pid_file.read_text(encoding="utf-8"))

    assert result.returncode == 0, result.stderr
    assert "interrupt-cleaned" in result.stdout
    assert _process_running(child_pid) is False
