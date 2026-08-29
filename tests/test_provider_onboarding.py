"""P1-7: installed-provider probes and recovery guidance."""

from __future__ import annotations

from birkin.executable_resolution import (
    CommandResolution,
    OutputMatch,
    ProbeAttempt,
    ProbeExecution,
    ProbeExpectation,
    ProbeFailureKind,
)


def _resolution(
    *,
    selected_path: str | None,
    failure: ProbeFailureKind | None = None,
) -> CommandResolution:
    attempt = ProbeAttempt(
        path=r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\codex.exe",
        execution=ProbeExecution(9009, "", "not installed"),
        failure_kind=failure,
    )
    return CommandResolution(
        command="codex",
        selected_path=selected_path,
        attempts=() if selected_path is not None else (attempt,),
        expectation=ProbeExpectation(OutputMatch.NONEMPTY_VERSION_OUTPUT),
    )


def test_codex_probe_reports_executed_binary_as_ready() -> None:
    from birkin import provider_onboarding

    class Resolver:
        def resolve(self, command: str) -> CommandResolution:
            assert command == "codex"
            return _resolution(selected_path=r"C:\tools\codex.exe")

    status = provider_onboarding.probe_codex(Resolver())

    assert status.usable is True
    assert status.path == r"C:\tools\codex.exe"
    assert status.issue is None


def test_codex_probe_distinguishes_nonfunctional_windows_shim() -> None:
    from birkin import provider_onboarding

    class Resolver:
        def resolve(self, command: str) -> CommandResolution:
            assert command == "codex"
            return _resolution(
                selected_path=None,
                failure=ProbeFailureKind.NON_FUNCTIONAL_SHIM,
            )

    status = provider_onboarding.probe_codex(Resolver())

    assert status.usable is False
    assert status.issue is provider_onboarding.CodexProbeIssue.NON_FUNCTIONAL_SHIM


def test_codex_probe_reports_missing_installation() -> None:
    from birkin import provider_onboarding

    class Resolver:
        def resolve(self, command: str) -> CommandResolution:
            assert command == "codex"
            return CommandResolution(
                command="codex",
                selected_path=None,
                attempts=(),
                expectation=ProbeExpectation(
                    OutputMatch.NONEMPTY_VERSION_OUTPUT,
                ),
            )

    status = provider_onboarding.probe_codex(Resolver())

    assert status.usable is False
    assert status.path is None
    assert status.issue is provider_onboarding.CodexProbeIssue.NOT_FOUND


def test_codex_install_command_uses_official_windows_installer() -> None:
    from birkin.provider_onboarding import codex_install_command

    command = codex_install_command("win32")

    assert "https://chatgpt.com/codex/install.ps1" in command
    assert "powershell" in command.lower()
