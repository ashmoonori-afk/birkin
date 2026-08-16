"""Subprocess argv helpers — no ``shell=True`` anywhere.

Passing ``shell=True`` with an interpolated command string is an injection risk
and a cross-platform quoting hazard. Instead:

- ``cli_argv(parts)`` launches a program from a *discrete* argv list. On Windows
  it routes through ``cmd /c`` so npm ``.cmd`` shims (``claude``, ``codex``)
  resolve via PATH; the args stay discrete, so there is no shell-string injection.
- ``shell_argv(command)`` is the *one intentional* place we run an arbitrary
  shell command *string* (the ``run_shell`` tool and user-approved shell jobs):
  it wraps the string in an explicit platform shell argv rather than ``shell=True``.
"""

from __future__ import annotations

import ntpath
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict

# cmd.exe re-parses these inside each argument even when argv is discrete, so a
# value like ``foo & calc`` smuggled into a CLI arg would chain a second command.
# We launch CLI shims through ``cmd /c`` (for ``.cmd`` PATH resolution) but never
# intend shell semantics for the args, so reject them on Windows. Free-form shell
# strings have their own intentional path (``shell_argv``), which this never gates.
_WIN_SHELL_METACHARS = frozenset("&|<>^")
_POSIX_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


@dataclass(frozen=True, slots=True)
class ShellCommand:
    """One bounded free-form shell execution request."""

    command: str
    cwd: Path | None
    timeout: int
    environment: dict[str, str]
    stdin: str | None = None
    hide_window: bool = False
    merge_stderr: bool = False


class ProcessHandle(Protocol):
    pid: int

    def kill(self) -> None: ...


class ManagedProcessTree(Protocol):
    def terminate(self, exit_code: int = 1) -> None: ...

    def close(self) -> None: ...


class PopenTreeKwargs(TypedDict, total=False):
    creationflags: int
    start_new_session: bool


def cli_argv(parts: list[str]) -> list[str]:
    """argv for launching a CLI program (handles Windows .cmd shims).

    Raises ``ValueError`` if a Windows arg carries cmd.exe metacharacters
    (``& | < > ^``) — see ``_WIN_SHELL_METACHARS``.
    """
    if os.name == "nt":
        for arg in parts[1:]:  # parts[0] is the program name (a trusted shim)
            if _WIN_SHELL_METACHARS.intersection(arg):
                message = (
                    "unsafe shell metacharacter (& | < > ^) in CLI argument "
                    f"on Windows: {arg!r}"
                )
                raise ValueError(message)
        program = parts[0]
        appdata = os.environ.get("APPDATA")
        if appdata and os.path.basename(program) == program:
            npm_shim = Path(appdata) / "npm" / f"{program}.cmd"
            if npm_shim.is_file():
                program = str(npm_shim)
        return ["cmd", "/c", program, *parts[1:]]
    return list(parts)


def shell_argv(command: str) -> list[str]:
    """argv for running an arbitrary shell command STRING via an explicit shell.

    Used only by ``run_shell`` and user-approved shell jobs — running a free-form
    command is the whole point there, so shell semantics are intentional.
    """
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot") or r"C:\Windows"
        return windows_shell_argv(command, system_root)
    return ["/bin/bash", "-c", command]


def windows_shell_argv(command: str, system_root: str) -> list[str]:
    """Build an AutoRun-free, UTF-8 argv for the Windows interpreter."""
    system32 = ntpath.join(system_root, "System32")
    executable = ntpath.join(system32, "cmd.exe")
    code_page = ntpath.join(system32, "chcp.com")
    return [
        executable,
        "/d",
        "/s",
        "/c",
        f"@{code_page} 65001>nul & {command}",
    ]


def windows_creation_flags(hide_window: bool) -> int:
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    if hide_window:
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return flags


def _runtime_bin_directories() -> tuple[Path, ...]:
    home = Path.home()
    return (
        Path(sys.executable).parent,
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        home / ".local" / "bin",
        home / ".volta" / "bin",
        home / ".bun" / "bin",
    )


def _writable_temp_directory(value: str | None) -> bool:
    if not value:
        return False
    directory = Path(value)
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot")
        if system_root:
            system = Path(system_root)
            if directory in (system, system / "System32"):
                return False
    if not directory.is_dir():
        return False
    try:
        with tempfile.NamedTemporaryFile(dir=directory):
            pass
    except OSError:
        return False
    return True


def _windows_temp_directory() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    candidates = (
        str(Path(local_app_data) / "Temp") if local_app_data else None,
        tempfile.gettempdir(),
    )
    for candidate in candidates:
        if candidate is not None and _writable_temp_directory(candidate):
            return candidate
    raise OSError("No writable Windows temporary directory")


def _normalized_shell_environment(
    source: dict[str, str],
) -> dict[str, str]:
    """Add only execution mechanics, without sourcing shell profiles."""
    env = dict(source)
    path_entries = [
        entry for entry in env.get("PATH", "").split(os.pathsep) if entry
    ]
    for directory in _runtime_bin_directories():
        value = str(directory)
        if directory.is_dir() and value not in path_entries:
            path_entries.append(value)
    env["PATH"] = os.pathsep.join(path_entries)

    if os.name == "nt":
        for name in ("SystemRoot", "ComSpec", "PATHEXT"):
            value = os.environ.get(name)
            if value:
                _ = env.setdefault(name, value)
        temp_dir = _windows_temp_directory()
        for name in ("TEMP", "TMP"):
            if not _writable_temp_directory(env.get(name)):
                env[name] = temp_dir
        env["PYTHONUTF8"] = "1"
    else:
        temp_dir = (
            env.get("TMPDIR")
            or env.get("TEMP")
            or env.get("TMP")
            or tempfile.gettempdir()
        )
        _ = env.setdefault("TMPDIR", temp_dir)
        _ = env.setdefault("TEMP", temp_dir)
        _ = env.setdefault("TMP", temp_dir)
    return env


def shell_env() -> dict[str, str]:
    """Environment for a free-form shell command."""
    return _normalized_shell_environment(dict(os.environ))


def run_shell_command(
    request: ShellCommand,
) -> subprocess.CompletedProcess[str]:
    """Run a shell request in an independently killable process tree."""
    argv = shell_argv(request.command)
    managed_tree: ManagedProcessTree | None = None
    if os.name == "nt":
        process, managed_tree = _spawn_managed_windows_shell(argv, request)
    else:
        process = _spawn_shell(argv, request)
    try:
        try:
            stdout, stderr = process.communicate(
                input=request.stdin,
                timeout=request.timeout,
            )
        except subprocess.TimeoutExpired:
            if managed_tree is not None:
                managed_tree.terminate(124)
            else:
                kill_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=10)
            raise subprocess.TimeoutExpired(
                argv,
                request.timeout,
                output=stdout,
                stderr=stderr,
            ) from None
        except (KeyboardInterrupt, SystemExit, OSError):
            if managed_tree is not None:
                managed_tree.terminate()
            else:
                kill_tree(process)
            try:
                _ = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                _ = process.communicate(timeout=10)
            raise
        return subprocess.CompletedProcess(
            argv,
            process.wait(),
            stdout,
            stderr,
        )
    finally:
        if managed_tree is not None:
            managed_tree.close()


def _spawn_managed_windows_shell(
    argv: list[str],
    request: ShellCommand,
) -> tuple[subprocess.Popen[str], ManagedProcessTree]:
    from birkin._winjob import WindowsJob, WindowsStartGate

    job = WindowsJob.create()
    gate: WindowsStartGate | None = None
    process: subprocess.Popen[str] | None = None
    assigned = False
    successful = False
    try:
        start_gate = WindowsStartGate.create()
        gate = start_gate
        process = _spawn_shell(start_gate.bootstrap_argv(argv), request)
        start_gate.wait_ready()
        job.assign(process.pid)
        assigned = True
        start_gate.release()
        successful = True
        return process, job
    except (OSError, RuntimeError, ValueError, KeyboardInterrupt, SystemExit):
        if assigned:
            job.terminate()
        elif process is not None:
            process.kill()
        if process is not None:
            try:
                _ = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        raise
    finally:
        if gate is not None:
            gate.close()
        if not successful:
            job.close()


def _spawn_shell(
    argv: list[str],
    request: ShellCommand,
) -> subprocess.Popen[str]:
    cwd = str(request.cwd) if request.cwd is not None else None
    if os.name == "nt":
        return subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.PIPE if request.stdin is not None else None,
            stdout=subprocess.PIPE,
            stderr=(
                subprocess.STDOUT
                if request.merge_stderr
                else subprocess.PIPE
            ),
            text=True,
            encoding="utf-8",
            errors="replace",
            env=request.environment,
            creationflags=windows_creation_flags(request.hide_window),
        )
    return subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.PIPE if request.stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=(
            subprocess.STDOUT if request.merge_stderr else subprocess.PIPE
        ),
        text=True,
        encoding="utf-8",
        errors="replace",
        env=request.environment,
        start_new_session=True,
    )


def popen_tree_kwargs() -> PopenTreeKwargs:
    """Return platform-native flags for a separately killable process tree."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_process_group(pid: int) -> bool:
    try:
        group = pid
        if group == os.getpgrp():
            return False
        os.killpg(group, _POSIX_KILL_SIGNAL)
        return True
    except (OSError, ProcessLookupError):
        return False


def kill_tree(proc: ProcessHandle | None) -> None:
    """Kill ``proc`` and its descendants.

    On Windows a CLI shim is launched through ``cmd /c`` (see ``cli_argv``), so
    ``proc.kill()`` only terminates ``cmd.exe`` and leaves the real child
    (``claude``/``codex`` → ``node``) running as an orphan. ``taskkill /T``
    walks the tree. POSIX children are started in their own session by
    :func:`popen_tree_kwargs`, so killing the process group reaps descendants
    without touching Birkin's own group. Best-effort: never raises."""
    if proc is None:
        return
    pid = proc.pid
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    if os.name != "nt" and kill_process_group(pid):
        return
    try:
        proc.kill()
    except OSError:
        pass


# Hook IDs of everything-claude-code (ECC) plugin hooks that must NOT run inside a
# birkin-spawned ``claude`` subprocess. The ECC interactive SessionStart hook
# injects an unrelated "Previous session summary" into context, which the model
# then surfaces on the first turn — leaking a session dump into gateway/Telegram
# replies. birkin supplies its own persona/memory/skills, so this hook is both
# wrong and harmful here. ECC reads ``ECC_DISABLED_HOOKS`` (see the plugin's
# ``scripts/lib/hook-flags.js``).
_BIRKIN_DISABLED_ECC_HOOKS = ("session:start",)


def claude_child_env() -> dict[str, str]:
    """Environment for a birkin-spawned ``claude`` subprocess.

    Inherits the parent environment and disables the ECC interactive SessionStart
    hook via ``ECC_DISABLED_HOOKS``, MERGING (never clobbering) any value the user
    already set. Used by :class:`birkin.claude_session.ClaudeStreamSession` (the
    warm gateway path) and ``llm.LLMClient._run_claude`` (the one-shot path).
    """
    env = dict(os.environ)
    disabled = [h.strip() for h in env.get("ECC_DISABLED_HOOKS", "").split(",")
                if h.strip()]
    for hook in _BIRKIN_DISABLED_ECC_HOOKS:
        if hook not in disabled:
            disabled.append(hook)
    env["ECC_DISABLED_HOOKS"] = ",".join(disabled)
    return env
