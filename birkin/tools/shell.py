"""Shell tool: run a command in the workspace with a timeout.

This is a powerful, dual-use capability intended for the user's own local
workspace. Output is captured and truncated; the command runs with the
context cwd unless an explicit ``cwd`` is given.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from . import Tool, ToolContext, ToolResult
from ..proc import shell_argv

# Memory bound only. The visible cap is applied by tools/spill.py, which saves
# the full output to disk first — slicing it away here would destroy it.
MAX_OUTPUT = 5_000_000
DEFAULT_TIMEOUT = 120


def _run_shell(inp: dict[str, Any], ctx: ToolContext) -> ToolResult:
    command = inp.get("command", "").strip()
    if not command:
        return ToolResult("Empty command", is_error=True)
    from .. import shellguard
    blocked = shellguard.check(command, ctx)
    if blocked is not None:
        return blocked
    cwd = Path(inp["cwd"]).expanduser() if inp.get("cwd") else ctx.cwd
    timeout = int(inp.get("timeout", DEFAULT_TIMEOUT))
    try:
        # Intentional shell semantics (this tool runs free-form commands), but
        # via an explicit platform shell argv — never shell=True. See proc.py.
        proc = subprocess.run(
            shell_argv(command), cwd=str(cwd), capture_output=True,
            text=True, errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(f"Command timed out after {timeout}s", is_error=True)
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n[output truncated at 5MB]"
    header = f"[exit {proc.returncode}]\n"
    return ToolResult(header + (out or "(no output)"), is_error=proc.returncode != 0)


def tools() -> list[Tool]:
    return [
        Tool(
            name="run_shell",
            description="Run a shell command in the workspace and return its "
                        "stdout/stderr and exit code. Use for builds, tests, git, "
                        "and file operations.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "description": "Working directory (optional)"},
                    "timeout": {"type": "integer", "description": "Seconds (default 120)"},
                },
                "required": ["command"],
            },
            fn=_run_shell,
        ),
    ]
