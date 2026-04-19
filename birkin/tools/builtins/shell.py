"""Shell command execution tool."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowlist: only these commands may be executed by default.
# ---------------------------------------------------------------------------
_ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "ls",
        "cat",
        "grep",
        "rg",
        "find",
        "git",
        "head",
        "tail",
        "wc",
        "pwd",
        "echo",
        "date",
        "which",
        "file",
        "stat",
    }
)

# Shell metacharacters that indicate chaining / redirection / subshells.
_SHELL_METACHARS: set[str] = {
    ";",
    "&&",
    "||",
    "|",
    ">",
    "<",
    "`",
    "$(",
    "${",
}

# ---------------------------------------------------------------------------
# Legacy blocklist (defense-in-depth, always active).
# ---------------------------------------------------------------------------

# Commands and patterns that are too dangerous to run.
_BLOCKED_PATTERNS: list[str] = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "chmod -R 777 /",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "init 0",
    "init 6",
]

# Commands that require explicit opt-in (not allowed by default).
_BLOCKED_PREFIXES: list[str] = [
    "sudo ",
    "su ",
]

_MAX_OUTPUT_CHARS = 50_000
_TIMEOUT_SECONDS = 30


def _build_allowed_set() -> frozenset[str]:
    """Return the effective allowed-command set, including env-var extensions."""
    extra = os.environ.get("BIRKIN_SHELL_ALLOWLIST", "").strip()
    if not extra:
        return _ALLOWED_COMMANDS
    additional = frozenset(tok.strip() for tok in extra.split(",") if tok.strip())
    return _ALLOWED_COMMANDS | additional


def _is_allowed(command: str) -> tuple[bool, str | None]:
    """Check whether *command* passes the allowlist and metachar rules.

    Returns ``(True, None)`` when allowed, or ``(False, reason)`` when denied.
    """
    # Sandbox bypass ----------------------------------------------------------
    if os.environ.get("BIRKIN_SHELL_SANDBOX", "").lower() == "off":
        _logger.warning(
            "BIRKIN_SHELL_SANDBOX=off — allowlist bypassed for: %s",
            command,
        )
        return True, None

    # Metacharacter scan (on raw string, before any parsing) ------------------
    for meta in _SHELL_METACHARS:
        if meta in command:
            return False, (f"Shell metacharacter '{meta}' is not permitted. Only simple, single commands are allowed.")

    # Command-name allowlist --------------------------------------------------
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return False, f"Failed to parse command: {exc}"

    if not tokens:
        return False, "Empty command."

    cmd_name = tokens[0].split("/")[-1]  # handle absolute paths like /usr/bin/ls
    allowed = _build_allowed_set()

    if cmd_name not in allowed:
        return False, (
            f"Command '{cmd_name}' is not in the allowed set. Allowed commands: {', '.join(sorted(allowed))}"
        )

    return True, None


def _is_blocked(command: str) -> str | None:
    """Return a reason string if the command is blocked, else None."""
    cmd_lower = command.strip().lower()

    for prefix in _BLOCKED_PREFIXES:
        if cmd_lower.startswith(prefix):
            return f"Commands starting with '{prefix.strip()}' are blocked for safety."

    for pattern in _BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            return f"Blocked dangerous pattern: '{pattern}'"

    return None


class ShellTool(Tool):
    """Execute shell commands in a subprocess."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="shell",
            description=(
                "Execute a shell command and return its stdout/stderr. "
                "Only allowlisted commands are permitted (ls, cat, grep, git, etc.). "
                "Shell metacharacters (pipes, chains, redirects) are rejected."
            ),
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="The shell command to execute.",
                    required=True,
                ),
            ],
            toolset="builtin",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        command = args.get("command", "").strip()
        if not command:
            return ToolOutput(success=False, output="", error="No command provided.")

        # Primary gate: allowlist + metacharacter rejection.
        allowed, deny_reason = _is_allowed(command)
        if not allowed:
            return ToolOutput(success=False, output="", error=deny_reason or "Command denied.")

        # Secondary gate (defense-in-depth): legacy blocklist.
        blocked_reason = _is_blocked(command)
        if blocked_reason:
            return ToolOutput(success=False, output="", error=blocked_reason)

        cwd = context.working_dir if context and context.working_dir else None

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            return ToolOutput(
                success=False,
                output="",
                error=f"Command timed out after {_TIMEOUT_SECONDS}s.",
            )
        except OSError as exc:
            return ToolOutput(success=False, output="", error=f"Failed to run command: {exc}")

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        combined = stdout
        if stderr:
            combined = f"{stdout}\n--- stderr ---\n{stderr}" if stdout else stderr

        # Truncate very long output.
        if len(combined) > _MAX_OUTPUT_CHARS:
            combined = combined[:_MAX_OUTPUT_CHARS] + "\n... [output truncated]"

        return_code = proc.returncode or 0
        if return_code != 0:
            return ToolOutput(
                success=False,
                output=combined,
                error=f"Command exited with code {return_code}.",
                metadata={"return_code": return_code},
            )

        return ToolOutput(
            success=True,
            output=combined,
            metadata={"return_code": return_code},
        )
