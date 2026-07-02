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
import subprocess
from typing import Any

# cmd.exe re-parses these inside each argument even when argv is discrete, so a
# value like ``foo & calc`` smuggled into a CLI arg would chain a second command.
# We launch CLI shims through ``cmd /c`` (for ``.cmd`` PATH resolution) but never
# intend shell semantics for the args, so reject them on Windows. Free-form shell
# strings have their own intentional path (``shell_argv``), which this never gates.
_WIN_SHELL_METACHARS = frozenset("&|<>^")


def cli_argv(parts: list[str]) -> list[str]:
    """argv for launching a CLI program (handles Windows .cmd shims).

    Raises ``ValueError`` if a Windows arg carries cmd.exe metacharacters
    (``& | < > ^``) — see ``_WIN_SHELL_METACHARS``.
    """
    if os.name == "nt":
        for arg in parts[1:]:  # parts[0] is the program name (a trusted shim)
            if _WIN_SHELL_METACHARS.intersection(arg):
                raise ValueError(
                    "unsafe shell metacharacter (& | < > ^) in CLI argument "
                    f"on Windows: {arg!r}")
        return ["cmd", "/c", *parts]
    return list(parts)


def shell_argv(command: str) -> list[str]:
    """argv for running an arbitrary shell command STRING via an explicit shell.

    Used only by ``run_shell`` and user-approved shell jobs — running a free-form
    command is the whole point there, so shell semantics are intentional.
    """
    if os.name == "nt":
        return ["cmd", "/c", command]
    return ["bash", "-lc", command]


def kill_tree(proc: "Any") -> None:
    """Kill ``proc`` and its descendants.

    On Windows a CLI shim is launched through ``cmd /c`` (see ``cli_argv``), so
    ``proc.kill()`` only terminates ``cmd.exe`` and leaves the real child
    (``claude``/``codex`` → ``node``) running as an orphan. ``taskkill /T``
    walks the tree. On POSIX ``proc.kill()`` already reaps the direct child.
    Best-effort: never raises."""
    if proc is None:
        return
    pid = getattr(proc, "pid", None)
    if os.name == "nt" and pid is not None:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=10)
            return
        except Exception:
            pass  # fall through to proc.kill()
    try:
        proc.kill()
    except Exception:
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
