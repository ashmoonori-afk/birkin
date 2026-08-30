"""Typed classification and scoped retry profiles for host policy blocks."""

from __future__ import annotations

import errno
import re
from dataclasses import dataclass
from pathlib import Path


_PERMISSION_MARKERS = (
    "access is denied",
    "accessdenied",
    "permission denied",
    "operation not permitted",
    "winerror 5",
    "errno 13",
    "eacces",
    "eperm",
)
_TEMP_MARKERS = (
    "\\temp\\",
    "/temp/",
    "temporary directory",
    "basetemp",
    "uv-cache",
    "uv_cache_dir",
)
_GIT_MARKERS = ("detected dubious ownership", "safe.directory")
_POWERSHELL_MARKERS = (
    "running scripts is disabled",
    "pssecurityexception",
    "cannot be loaded because it is not digitally signed",
)
_TEMP_COMMANDS = frozenset({
    "bun",
    "bunx",
    "pip",
    "py",
    "pytest",
    "python",
    "uv",
})


@dataclass(frozen=True, slots=True)
class ApprovalRequiredError(RuntimeError):
    """A discretionary Birkin policy block that a human may override once."""

    gate: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def is_permission_denial(value: object) -> bool:
    """Return whether a native value contains a known permission denial."""
    normalized = str(value).casefold()
    return any(marker in normalized for marker in _PERMISSION_MARKERS)


def permission_denial_summary() -> str:
    """Return the canonical summary for an observed permission denial."""
    return _PERMISSION_MARKERS[0]


def permission_block(exc: OSError) -> ApprovalRequiredError | None:
    """Convert OS permission failures into an approval-eligible block."""
    if isinstance(exc, PermissionError) or exc.errno in {
        errno.EACCES,
        errno.EPERM,
        errno.EROFS,
    }:
        return ApprovalRequiredError("os_permission", str(exc))
    if is_permission_denial(exc):
        return ApprovalRequiredError("os_permission", str(exc))
    return None


def diagnostic_block(
    text: str,
    *,
    tool: str = "",
    command: str = "",
) -> ApprovalRequiredError | None:
    """Recognize policy output only when its native command context agrees."""
    normalized = text.casefold()
    if (
        tool in {"write_file", "edit_file"}
        and "approval-required[control_plane]" in normalized
    ):
        return ApprovalRequiredError(
            "control_plane",
            "Birkin control-plane policy blocked the file operation",
        )
    if tool != "run_shell":
        return None
    command_name = _command_name(command)
    if (
        is_permission_denial(normalized)
        and any(marker in normalized for marker in _TEMP_MARKERS)
        and command_name in _TEMP_COMMANDS
    ):
        return ApprovalRequiredError(
            "local_temp_policy",
            "Default cache or temporary storage was denied",
        )
    if command_name == "git" and any(
        marker in normalized for marker in _GIT_MARKERS
    ):
        return ApprovalRequiredError(
            "git_safe_directory",
            "Git repository ownership policy blocked the command",
        )
    if is_powershell_execution_policy_failure(text, command):
        return ApprovalRequiredError(
            "powershell_execution_policy",
            "PowerShell execution policy blocked the command",
        )
    return None


def is_powershell_execution_policy_failure(text: str, command: str) -> bool:
    """Return whether a diagnostic binds a PowerShell policy block to command."""
    normalized = text.casefold()
    if not any(marker in normalized for marker in _POWERSHELL_MARKERS):
        return False
    command_name = _command_name(command)
    if command_name in {"powershell", "pwsh"}:
        return True
    leading_name = (
        command.strip().split(maxsplit=1)[0].strip("\"'")
        .replace("\\", "/").rsplit("/", 1)[-1]
    )
    if "." in leading_name:
        return False
    script_name = re.escape(f"{command_name}.ps1")
    return bool(command_name) and re.search(
        rf"(?<![\w.-]){script_name}(?![\w.-])",
        normalized,
    ) is not None


def retry_environment(gate: str, cwd: Path) -> dict[str, str]:
    """Return only per-process overrides sealed into an approved retry."""
    if gate == "git_safe_directory":
        return {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": str(cwd),
        }
    if gate == "powershell_execution_policy":
        return {"PSExecutionPolicyPreference": "Bypass"}
    if gate == "local_temp_policy":
        return {
            "TEMP": str(cwd / ".birkin-tmp"),
            "TMP": str(cwd / ".birkin-tmp"),
            "UV_CACHE_DIR": str(cwd / ".uv-cache"),
        }
    return {}


def _command_name(command: str) -> str:
    first = command.strip().split(maxsplit=1)[0] if command.strip() else ""
    return first.strip("\"'").replace("\\", "/").rsplit("/", 1)[-1] \
        .casefold().removesuffix(".exe").removesuffix(".cmd")
