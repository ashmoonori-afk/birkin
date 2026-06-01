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
