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

import os
import signal
import subprocess
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


class ProcessHandle(Protocol):
    pid: int

    def kill(self) -> None: ...


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
        return ["cmd", "/c", command]
    return ["bash", "-lc", command]


def shell_env() -> dict[str, str]:
    """Environment for a free-form shell command."""
    env = dict(os.environ)
    if os.name == "nt":
        temp_dir = tempfile.gettempdir()
        env["TEMP"] = temp_dir
        env["TMP"] = temp_dir
    return env


def run_shell_command(
    request: ShellCommand,
) -> subprocess.CompletedProcess[str]:
    """Run a shell request in an independently killable process tree."""
    argv = shell_argv(request.command)
    process = _spawn_shell(argv, request)
    try:
        stdout, stderr = process.communicate(timeout=request.timeout)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            argv,
            request.timeout,
            output=stdout,
            stderr=stderr,
        ) from None
    return subprocess.CompletedProcess(
        argv,
        process.wait(),
        stdout,
        stderr,
    )


def _spawn_shell(
    argv: list[str],
    request: ShellCommand,
) -> subprocess.Popen[str]:
    cwd = str(request.cwd) if request.cwd is not None else None
    if os.name == "nt":
        return subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=request.environment,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env=request.environment,
        start_new_session=True,
    )


def popen_tree_kwargs() -> PopenTreeKwargs:
    """Return platform-native flags for a separately killable process tree."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_posix_tree(pid: int) -> bool:
    try:
        group = os.getpgid(pid)
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
    if os.name != "nt" and _kill_posix_tree(pid):
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
