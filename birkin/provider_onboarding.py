"""Executable provider probes and first-run recovery guidance."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol, final

from .executable_resolution import (
    CommandResolution,
    ExecutableResolver,
    ProbeFailureKind,
)
from typing_extensions import assert_never


@final
class CodexProbeIssue(str, Enum):
    NOT_FOUND = "not_found"
    NON_FUNCTIONAL_SHIM = "non_functional_shim"
    START_FAILED = "start_failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class CodexProviderStatus:
    usable: bool
    path: str | None
    issue: CodexProbeIssue | None


@final
class CodexRecoveryAction(Enum):
    RETRY = "retry"
    CHOOSE_PROVIDER = "choose_provider"


CODEX_RECOVERY_OPTIONS: Final[tuple[str, str]] = (
    "설치 후 다시 확인",
    "다른 프로바이더 선택",
)


class CommandResolver(Protocol):
    def resolve(self, command: str) -> CommandResolution: ...


def probe_codex(
    resolver: CommandResolver | None = None,
) -> CodexProviderStatus:
    """Execute ``codex --version`` and classify the observed result."""
    resolution = (resolver or ExecutableResolver()).resolve("codex")
    if resolution.usable:
        return CodexProviderStatus(True, resolution.selected_path, None)
    if not resolution.attempts:
        return CodexProviderStatus(False, None, CodexProbeIssue.NOT_FOUND)
    match resolution.attempts[0].failure_kind:
        case ProbeFailureKind.NON_FUNCTIONAL_SHIM:
            issue = CodexProbeIssue.NON_FUNCTIONAL_SHIM
        case ProbeFailureKind.START_FAILED:
            issue = CodexProbeIssue.START_FAILED
        case ProbeFailureKind.TIMED_OUT:
            issue = CodexProbeIssue.TIMED_OUT
        case None:
            issue = CodexProbeIssue.NOT_FOUND
        case _:
            assert_never(resolution.attempts[0].failure_kind)
    return CodexProviderStatus(False, None, issue)


def codex_install_command(platform_name: str | None = None) -> str:
    """Return the official Codex installer command for this platform."""
    platform = platform_name or sys.platform
    if platform == "win32":
        return (
            'powershell -ExecutionPolicy ByPass -c "irm '
            'https://chatgpt.com/codex/install.ps1 | iex"'
        )
    return "curl -fsSL https://chatgpt.com/codex/install.sh | sh"


def codex_recovery_text(
    status: CodexProviderStatus,
    platform_name: str | None = None,
) -> str:
    """Render a localized, actionable recovery message."""
    match status.issue:
        case CodexProbeIssue.NON_FUNCTIONAL_SHIM:
            reason = "Codex 경로가 실행되지 않는 Windows shim입니다."
        case CodexProbeIssue.START_FAILED:
            reason = "Codex 실행 파일을 시작할 수 없습니다."
        case CodexProbeIssue.TIMED_OUT:
            reason = "Codex 설치 확인이 시간 안에 끝나지 않았습니다."
        case CodexProbeIssue.NOT_FOUND | None:
            reason = "Codex CLI가 설치되어 있지 않습니다."
        case _:
            assert_never(status.issue)
    command = codex_install_command(platform_name)
    return (
        f"{reason}\n"
        f"  설치: {command}\n"
        "  설치 후 새 터미널에서 `codex`를 실행하고 "
        "Sign in with ChatGPT를 완료하세요."
    )


def recovery_action(index: int) -> CodexRecoveryAction:
    """Parse the stable recovery menu position."""
    return (
        CodexRecoveryAction.RETRY
        if index == 0
        else CodexRecoveryAction.CHOOSE_PROVIDER
    )
