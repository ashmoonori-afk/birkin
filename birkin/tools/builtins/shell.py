"""Shell command execution tool."""

from __future__ import annotations

import asyncio
from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec

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
                "Dangerous commands (rm -rf /, sudo, etc.) are blocked."
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
        except asyncio.TimeoutError:
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
