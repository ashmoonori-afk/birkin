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
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict

from typing_extensions import Unpack

from birkin.operation_policy import is_powershell_execution_policy_failure

# cmd.exe re-parses these inside each argument even when argv is discrete, so a
# value like ``foo & calc`` smuggled into a CLI arg would chain a second command.
# We launch CLI shims through ``cmd /c`` (for ``.cmd`` PATH resolution) but never
# intend shell semantics for the args, so reject them on Windows. Free-form shell
# strings have their own intentional path (``shell_argv``), which this never gates.
_WIN_SHELL_METACHARS = frozenset("&|<>^")
_WINDOWS_CREATE_SUSPENDED = 0x00000004
_WINDOWS_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_WINDOWS_ACCESS_DENIED = 5
_WINDOWS_NATIVE_EXTENSIONS = (".com", ".exe", ".bat", ".cmd")
_WINDOWS_NATIVE_PATH_METACHARS = frozenset("%!&|<>^()")
_POSIX_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)
_SHELL_ENVIRONMENT = frozenset({
    "COLORTERM",
    "ComSpec",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "SHELL",
    "SystemRoot",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USER",
    "USERPROFILE",
    "WINDIR",
})


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


class PopenDetachedKwargs(TypedDict, total=False):
    close_fds: bool
    stdin: int
    stdout: int
    stderr: int


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
        system_root = os.environ.get("SystemRoot")
        if not system_root:
            raise OSError("SystemRoot is required for Windows shell execution")
        return windows_shell_argv(command, system_root)
    return ["/bin/bash", "-c", command]


def windows_system_executable(
    name: str,
    system_root: str | None = None,
) -> str | None:
    root = system_root or os.environ.get("SystemRoot")
    if not root:
        return None
    return ntpath.join(root, "System32", name)


def windows_shell_argv(command: str, system_root: str) -> list[str]:
    """Build an AutoRun-free, UTF-8 argv for the Windows interpreter."""
    executable = windows_system_executable("cmd.exe", system_root)
    code_page = windows_system_executable("chcp.com", system_root)
    if executable is None or code_page is None:
        raise OSError("SystemRoot is required for Windows shell execution")
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


def shell_env(
    *,
    allowlist: Iterable[str] = (),
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Minimal environment for a free-form shell command."""
    values = os.environ if source is None else source
    requested = frozenset(allowlist)
    names = (
        frozenset(values)
        if "*" in requested
        else _SHELL_ENVIRONMENT | requested
    )
    selected = {
        name: value
        for name, value in values.items()
        if name in names
    }
    return _normalized_shell_environment(selected)


def run_shell_command(
    request: ShellCommand,
) -> subprocess.CompletedProcess[str]:
    """Run a shell request in an independently killable process tree."""
    deadline = time.monotonic() + request.timeout
    original = _run_shell_attempt(
        shell_argv(request.command),
        request,
        deadline,
    )
    if (
        os.name != "nt"
        or original.returncode == 0
        or not is_powershell_execution_policy_failure(
            original.stderr or "",
            request.command,
        )
    ):
        return original
    for command in _windows_native_shim_commands(request):
        result = _run_shell_attempt(
            shell_argv(command),
            request,
            deadline,
        )
        if result.returncode == 0:
            return result
    return original


def _run_shell_attempt(
    argv: list[str],
    request: ShellCommand,
    deadline: float,
) -> subprocess.CompletedProcess[str]:
    """Run one managed attempt within the request's monotonic deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(argv, request.timeout)
    managed_tree: ManagedProcessTree | None = None
    if os.name == "nt":
        process, managed_tree = spawn_managed_windows_shell(argv, request)
    else:
        process = _spawn_shell(argv, request)
    try:
        try:
            stdout, stderr = process.communicate(
                input=request.stdin,
                timeout=remaining,
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


def _windows_native_shim_commands(request: ShellCommand) -> tuple[str, ...]:
    """Return safe absolute native replacements for one bare command token."""
    separator = next(
        (index for index, char in enumerate(request.command) if char.isspace()),
        len(request.command),
    )
    name = request.command[:separator]
    if (
        not name
        or not all(
            char.isascii() and (char.isalnum() or char in "_-")
            for char in name
        )
        or ntpath.splitext(name)[1]
    ):
        return ()
    suffix = request.command[separator:]
    cwd = (request.cwd or Path.cwd()).resolve()
    directories = [cwd]
    for value in request.environment.get("PATH", "").split(os.pathsep):
        if not value:
            continue
        directory = Path(value)
        directories.append(
            directory.resolve()
            if directory.is_absolute()
            else (cwd / directory).resolve()
        )

    commands: list[str] = []
    seen: set[str] = set()
    for directory in directories:
        for extension in _WINDOWS_NATIVE_EXTENSIONS:
            candidate = (directory / f"{name}{extension}").resolve()
            normalized = str(candidate).casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            candidate_text = str(candidate)
            if (
                not candidate.is_file()
                or _WINDOWS_NATIVE_PATH_METACHARS.intersection(candidate_text)
            ):
                continue
            executable = (
                f'"{candidate_text}"'
                if any(char.isspace() for char in candidate_text)
                else candidate_text
            )
            commands.append(f"{executable}{suffix}")
    return tuple(commands)


def spawn_managed_windows_shell(
    argv: list[str],
    request: ShellCommand,
) -> tuple[subprocess.Popen[str], ManagedProcessTree]:
    from birkin._winjob import WindowsJob

    job = WindowsJob.create()
    process: subprocess.Popen[str] | None = None
    successful = False
    try:
        process = _spawn_shell(argv, request, suspended=True)
        job.assign(process.pid)
        job.resume(process.pid)
        successful = True
        return process, job
    except (OSError, RuntimeError, ValueError, KeyboardInterrupt, SystemExit):
        if process is not None:
            process.kill()
            _ = process.wait(timeout=10)
        raise
    finally:
        if not successful:
            job.close()


def _spawn_shell(
    argv: list[str],
    request: ShellCommand,
    *,
    suspended: bool = False,
) -> subprocess.Popen[str]:
    cwd = str(request.cwd) if request.cwd is not None else None
    if os.name == "nt":
        creationflags = windows_creation_flags(request.hide_window)
        if suspended:
            creationflags |= _WINDOWS_CREATE_SUSPENDED
        popen_argv: list[str] | str = argv
        executable: str | None = None
        is_cmd_shell = (
            len(argv) == 5
            and ntpath.basename(argv[0]).casefold() == "cmd.exe"
            and [part.casefold() for part in argv[1:4]]
            == ["/d", "/s", "/c"]
        )
        if is_cmd_shell:
            popen_argv = f"{subprocess.list2cmdline(argv[:4])} {argv[4]}"
            executable = argv[0]
        return subprocess.Popen(
            popen_argv,
            executable=executable,
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
            creationflags=creationflags,
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


def popen_detached(
    argv: Sequence[str],
    **kwargs: Unpack[PopenDetachedKwargs],
) -> subprocess.Popen[bytes]:
    """Spawn a process that outlives this one.

    On Windows the child breaks out of the parent's job object so a supervisor
    (nssm, Task Scheduler, CI) tearing that job down does not take the spawned
    process with it. A job created without ``JOB_OBJECT_LIMIT_BREAKAWAY_OK``
    refuses the flag with ``WinError 5``, so retry inside the job rather than
    failing the spawn outright. POSIX just needs its own session.
    """
    if os.name != "nt":
        return subprocess.Popen(argv, start_new_session=True, **kwargs)
    group = windows_creation_flags(hide_window=False)
    breakaway = getattr(
        subprocess,
        "CREATE_BREAKAWAY_FROM_JOB",
        _WINDOWS_CREATE_BREAKAWAY_FROM_JOB,
    )
    try:
        return subprocess.Popen(argv, creationflags=group | breakaway, **kwargs)
    except OSError as exc:
        if getattr(exc, "winerror", None) != _WINDOWS_ACCESS_DENIED:
            raise
        return subprocess.Popen(argv, creationflags=group, **kwargs)


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
        taskkill = windows_system_executable("taskkill.exe")
        if taskkill is not None:
            try:
                result = subprocess.run(
                    [taskkill, "/F", "/T", "/PID", str(pid)],
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
