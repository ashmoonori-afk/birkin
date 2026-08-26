"""Shell tool: run a command in the workspace with a timeout.

This is a powerful, dual-use capability intended for the user's own local
workspace. Output is captured and truncated; the command runs with the
context cwd unless an explicit ``cwd`` is given.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Protocol, TypeGuard, cast

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


class _ConfigValue(Protocol):
    """Opaque input that must be narrowed before use."""


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    text = _text(stdout)
    error = _text(stderr)
    return text + (("\n[stderr]\n" + error) if error else "")


def _is_string_list(value: _ConfigValue) -> TypeGuard[list[str]]:
    if not isinstance(value, list):
        return False
    entries = cast(list[object], value)
    return all(isinstance(entry, str) for entry in entries)


def _run_shell(inp: dict[str, _ConfigValue], ctx: ToolContext) -> ToolResult:
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
    try:
        workspace = ctx.cwd.expanduser().resolve(strict=True)
        roots = [workspace]
        shell_cfg_value = cast(_ConfigValue, ctx.cfg.get("shell", {}))
        if not isinstance(shell_cfg_value, dict):
            return ToolResult(
                "Invalid shell configuration",
                is_error=True,
            )
        shell_cfg = cast(dict[object, object], shell_cfg_value)
        raw_roots = cast(_ConfigValue, shell_cfg.get("extra_roots", []))
        if not _is_string_list(raw_roots):
            return ToolResult(
                "Invalid shell.extra_roots configuration",
                is_error=True,
            )
        for value in raw_roots:
            root = Path(value).expanduser()
            if not root.is_absolute():
                root = workspace / root
            roots.append(root.resolve(strict=True))
        candidate = (
            Path(cwd_value).expanduser()
            if isinstance(cwd_value, str) and cwd_value
            else workspace
        )
        if not candidate.is_absolute():
            candidate = workspace / candidate
        cwd = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return ToolResult("Shell cwd does not exist", is_error=True)
    if not cwd.is_dir():
        return ToolResult("Shell cwd is not a directory", is_error=True)
    if not any(cwd == root or cwd.is_relative_to(root) for root in roots):
        return ToolResult(
            "Shell cwd is outside the configured workspace roots",
            is_error=True,
        )
    timeout_value = inp.get("timeout", DEFAULT_TIMEOUT)
    timeout = (
        timeout_value
        if isinstance(timeout_value, int) and not isinstance(timeout_value, bool)
        else DEFAULT_TIMEOUT
    )
    raw_allowlist = cast(
        _ConfigValue,
        shell_cfg.get("env_passthrough", []),
    )
    if not _is_string_list(raw_allowlist):
        return ToolResult(
            "Invalid shell.env_passthrough configuration",
            is_error=True,
        )
    environment = shell_env(allowlist=raw_allowlist)
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
