"""Shell tool: run a command in the workspace with a timeout.

This is a powerful, dual-use capability intended for the user's own local
workspace. Output is captured and truncated; the command runs with the
context cwd unless an explicit ``cwd`` is given.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import cast

from ..operation_policy import ApprovalRequiredError
from ..proc import ShellCommand, run_shell_command, shell_env
from ._types import Tool, ToolContext, ToolResult

# Memory bound only. The visible cap is applied by tools/spill.py, which saves
# the full output to disk first — slicing it away here would destroy it.
MAX_OUTPUT = 5_000_000
DEFAULT_TIMEOUT = 120
_POWERSHELL_SEGMENT = re.compile(
    (
        r"(?:^|[;&|]\s*|\bcmd(?:\.exe)?\s+/[ck]\s+)"
        + r"(?:call\s+)?(?:\"?[^\s\";&|]*[\\/])?"
        + r"(?:powershell|pwsh)(?:\.exe)?(?:\"|\s|$)"
    ),
    re.IGNORECASE,
)


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    text = _text(stdout)
    error = _text(stderr)
    return text + (("\n[stderr]\n" + error) if error else "")


def _run_shell(inp: dict[str, object], ctx: ToolContext) -> ToolResult:
    command_value = inp.get("command")
    command = command_value.strip() if isinstance(command_value, str) else ""
    if not command:
        return ToolResult("Empty command", is_error=True)
    from .. import shellguard
    blocked = cast(ToolResult | None, shellguard.check(command, ctx))
    if blocked is not None:
        return blocked
    if (
        _POWERSHELL_SEGMENT.search(command)
        and ctx.cfg.get("allow_powershell") is not True
        and not ctx.approved_operation
    ):
        from ..operation_approval import queue_operation

        return queue_operation(
            "run_shell",
            inp,
            ctx,
            ApprovalRequiredError(
                "powershell_opt_in",
                "PowerShell execution requires explicit operator opt-in",
            ),
        )
    cwd_value = inp.get("cwd")
    cwd = (
        Path(cwd_value).expanduser()
        if isinstance(cwd_value, str) and cwd_value
        else ctx.cwd
    )
    timeout_value = inp.get("timeout", DEFAULT_TIMEOUT)
    timeout = (
        timeout_value
        if isinstance(timeout_value, int) and not isinstance(timeout_value, bool)
        else DEFAULT_TIMEOUT
    )
    environment = shell_env()
    approved_environment = inp.get("_approved_env")
    if ctx.approved_operation and isinstance(approved_environment, dict):
        supplied = cast(dict[object, object], approved_environment)
        allowed = {
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_KEY_0",
            "GIT_CONFIG_VALUE_0",
            "PSExecutionPolicyPreference",
            "TEMP",
            "TMP",
            "UV_CACHE_DIR",
        }
        if (
            any(not isinstance(key, str) or key not in allowed for key in supplied)
            or any(not isinstance(value, str) for value in supplied.values())
        ):
            return ToolResult(
                "Invalid approved operation environment",
                is_error=True,
            )
        approved = cast(dict[str, str], supplied)
        environment.update(approved)
        for key in ("TEMP", "TMP", "UV_CACHE_DIR"):
            value = approved.get(key)
            if value:
                Path(value).mkdir(parents=True, exist_ok=True)
    try:
        proc = run_shell_command(
            ShellCommand(
                command=command,
                cwd=cwd,
                timeout=timeout,
                environment=environment,
            )
        )
    except subprocess.TimeoutExpired as exc:
        partial = _output(exc.stdout, exc.stderr)
        suffix = f"\n{partial}" if partial else ""
        return ToolResult(
            f"Command timed out after {timeout}s{suffix}",
            is_error=True,
        )
    out = _output(proc.stdout, proc.stderr)
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n[output truncated at 5MB]"
    header = f"[exit {proc.returncode}]\n"
    return ToolResult(header + (out or "(no output)"), is_error=proc.returncode != 0)


def tools() -> list[Tool]:
    return [
        Tool(
            name="run_shell",
            description="Run a shell command in the workspace and return its stdout/stderr and exit code. Use for builds, tests, git, and file operations. On Windows this uses cmd.exe; PowerShell requires allow_powershell=true or one exact manual approval.",
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
