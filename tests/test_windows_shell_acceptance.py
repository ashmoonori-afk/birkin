"""Real-shell acceptance tests shared by POSIX and native Windows CI."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from birkin.tools import ToolContext, ToolResult
from birkin.tools import shell as shell_mod


def _command(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _run(command: str, cwd: Path, timeout: int = 10) -> ToolResult:
    tool = next(tool for tool in shell_mod.tools() if tool.name == "run_shell")
    context = ToolContext(cfg={}, client=None, cwd=cwd)
    return tool.fn({"command": command, "timeout": timeout}, context)


def _write_script(path: Path, source: str) -> None:
    _ = path.write_text(source, encoding="utf-8")


def _source(*lines: str) -> str:
    return "\n".join((*lines, ""))


def _process_running(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return f'"{pid}"' in result.stdout
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def test_ordinary_command_and_unicode_spaced_cwd(tmp_path: Path) -> None:
    workspace = tmp_path / "한글 workspace"
    workspace.mkdir()
    script = workspace / "show cwd.py"
    _write_script(
        script,
        "from pathlib import Path\nprint(f'ordinary-ok:{Path.cwd()}')\n",
    )

    result = _run(_command([sys.executable, str(script)]), workspace)

    assert result.is_error is False
    assert f"ordinary-ok:{workspace}" in result.content
    assert "[exit 0]" in result.content


def test_pipe_redirect_and_quoted_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "quoted workspace"
    workspace.mkdir()
    producer = workspace / "produce words.py"
    consumer = workspace / "consume words.py"
    output = workspace / "redirected result.txt"
    _write_script(producer, "print('quoted pipe ok')\n")
    _write_script(
        consumer,
        "import sys\nprint(sys.stdin.read().strip().upper())\n",
    )
    command = (
        f"{_command([sys.executable, str(producer)])} | "
        f"{_command([sys.executable, str(consumer)])} > "
        f"{_command([str(output)])}"
    )

    result = _run(command, workspace)

    assert result.is_error is False
    assert output.read_text(encoding="utf-8").strip() == "QUOTED PIPE OK"


def test_environment_stdout_stderr_and_exit_propagate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_SHELL_SENTINEL", "inherited-ok")
    script = tmp_path / "streams.py"
    _write_script(
        script,
        _source(
            "import os, sys",
            "print(os.environ['BIRKIN_SHELL_SENTINEL'])",
            "print('stderr-ok', file=sys.stderr)",
            "raise SystemExit(7)",
        ),
    )

    result = _run(_command([sys.executable, str(script)]), tmp_path)

    assert result.is_error is True
    assert "inherited-ok" in result.content
    assert "[stderr]\nstderr-ok" in result.content
    assert "[exit 7]" in result.content


@pytest.mark.skipif(os.name != "nt", reason="native Windows TEMP/TMP contract")
def test_windows_temp_and_runtime_smokes(tmp_path: Path) -> None:
    temp_probe = tmp_path / "temp probe.py"
    _write_script(
        temp_probe,
        _source(
            "import os",
            "from pathlib import Path",
            "for name in ('TEMP', 'TMP'):",
            "    root = Path(os.environ[name])",
            "    probe = root / f'birkin-{name.lower()}-probe.txt'",
            "    probe.write_text('ok', encoding='utf-8')",
            "    probe.unlink()",
            "print('temp-ok')",
        ),
    )
    commands = [
        _command([sys.executable, str(temp_probe)]),
        "python --version",
        "npm --version",
        "bun --version",
    ]
    shim = tmp_path / "birkin-smoke.cmd"
    _ = shim.write_text("@echo cmd-shim-ok\r\n", encoding="utf-8")
    commands.append(_command([str(shim)]))

    for command in commands:
        result = _run(command, tmp_path)
        assert result.is_error is False, result.content


def test_timeout_preserves_output_and_cleans_descendants(
    tmp_path: Path,
) -> None:
    script = tmp_path / "descendant.py"
    _write_script(
        script,
        _source(
            "import subprocess, sys",
            "from pathlib import Path",
            "child = subprocess.Popen([",
            "    sys.executable, '-c', 'import time; time.sleep(6)'",
            "])",
            "Path('child.pid').write_text(str(child.pid), encoding='utf-8')",
            "print('before-timeout', flush=True)",
            "raise SystemExit(child.wait())",
        ),
    )

    started = time.monotonic()
    result = _run(_command([sys.executable, str(script)]), tmp_path, timeout=1)
    elapsed = time.monotonic() - started
    child_pid = int((tmp_path / "child.pid").read_text(encoding="utf-8"))

    assert result.is_error is True
    assert isinstance(result.content, str)
    assert "before-timeout" in result.content
    assert "timed out" in result.content.lower()
    assert elapsed < 4
    assert _process_running(child_pid) is False
