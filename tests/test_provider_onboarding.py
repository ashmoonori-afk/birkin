"""P1-7: installed-provider probes and recovery guidance."""

from __future__ import annotations

import pytest

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

    status = provider_onboarding.probe_codex(
        Resolver(),
        which=lambda _: "codex",
    )

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

    status = provider_onboarding.probe_codex(
        Resolver(),
        which=lambda _: "codex",
    )

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

    status = provider_onboarding.probe_codex(
        Resolver(),
        which=lambda _: "codex",
    )

    assert status.usable is False
    assert status.path is None
    assert status.issue is provider_onboarding.CodexProbeIssue.NOT_FOUND


def test_codex_probe_stops_when_shutil_which_finds_no_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin import provider_onboarding

    class Resolver:
        def resolve(self, command: str) -> CommandResolution:
            raise AssertionError(f"resolver must not run for missing {command}")

    monkeypatch.setattr(provider_onboarding.shutil, "which", lambda _: None)

    status = provider_onboarding.probe_codex(Resolver())

    assert status.usable is False
    assert status.path is None
    assert status.issue is provider_onboarding.CodexProbeIssue.NOT_FOUND


def test_codex_install_command_uses_official_windows_installer() -> None:
    from birkin.provider_onboarding import codex_install_command

    command = codex_install_command("win32")

    assert "https://chatgpt.com/codex/install.ps1" in command
    assert "powershell" in command.lower()


def test_probe_claude_found() -> None:
    from birkin import provider_onboarding

    class Resolver:
        def resolve(self, command: str) -> CommandResolution:
            assert command == "claude"
            return _resolution(selected_path=r"C:\tools\claude.exe")

    status = provider_onboarding.probe_claude(
        Resolver(),
        which=lambda command: command,
    )

    assert status.usable is True
    assert status.path == r"C:\tools\claude.exe"
    assert status.issue is None


def test_probe_claude_not_found() -> None:
    from birkin import provider_onboarding

    class Resolver:
        def resolve(self, command: str) -> CommandResolution:
            raise AssertionError(f"resolver must not run for missing {command}")

    status = provider_onboarding.probe_claude(
        Resolver(),
        which=lambda _command: None,
    )

    assert status.usable is False
    assert status.path is None
    assert status.issue is provider_onboarding.CodexProbeIssue.NOT_FOUND


def test_probe_claude_non_functional_shim() -> None:
    from birkin import provider_onboarding

    class Resolver:
        def resolve(self, command: str) -> CommandResolution:
            assert command == "claude"
            return _resolution(
                selected_path=None,
                failure=ProbeFailureKind.NON_FUNCTIONAL_SHIM,
            )

    status = provider_onboarding.probe_claude(
        Resolver(),
        which=lambda command: command,
    )

    assert status.usable is False
    assert status.path is None
    assert status.issue is provider_onboarding.CodexProbeIssue.NON_FUNCTIONAL_SHIM


def test_auto_detect_engines_prefers_codex() -> None:
    from birkin import provider_onboarding

    class Resolver:
        def resolve(self, command: str) -> CommandResolution:
            return _resolution(selected_path=rf"C:\tools\{command}.exe")

    detected = provider_onboarding.detect_engines(
        Resolver(),
        which=lambda command: command,
    )

    assert detected.codex.usable is True
    assert detected.claude.usable is True
    assert detected.preferred == "codex-cli"


def test_auto_detect_engines_falls_back_to_claude() -> None:
    from birkin import provider_onboarding

    class Resolver:
        def resolve(self, command: str) -> CommandResolution:
            if command == "codex":
                return _resolution(
                    selected_path=None,
                    failure=ProbeFailureKind.NON_FUNCTIONAL_SHIM,
                )
            return _resolution(selected_path=r"C:\tools\claude.exe")

    detected = provider_onboarding.detect_engines(
        Resolver(),
        which=lambda command: command,
    )

    assert detected.codex.usable is False
    assert detected.claude.usable is True
    assert detected.preferred == "claude-cli"


def test_auto_detect_none_found_keeps_default_and_recovery_reachable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from birkin import onboarding, provider_onboarding

    missing = provider_onboarding.CodexProviderStatus(
        False,
        None,
        provider_onboarding.CodexProbeIssue.NOT_FOUND,
    )
    choices = iter([0, 1, 1])
    provider_defaults: list[int] = []

    monkeypatch.setattr(
        provider_onboarding,
        "detect_engines",
        lambda: provider_onboarding.DetectedEngines(missing, missing, None),
    )
    monkeypatch.setattr(provider_onboarding, "probe_codex", lambda: missing)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    def select(_prompt: str, options: list[str], default: int = 0) -> int:
        if options == ["codex-cli", "claude-cli", "anthropic", "openai"]:
            provider_defaults.append(default)
        return next(choices)

    monkeypatch.setattr(onboarding.menu, "select", select)

    assert (
        onboarding._choose_provider("codex-cli", first_run=True) == "claude-cli"
    )
    assert provider_defaults == [0, 0]
    output = capsys.readouterr().out
    assert (
        "  ! 로컬에서 Codex CLI나 Claude CLI를 찾지 못했습니다. "
        "아래에서 프로바이더를 직접 선택하세요."
    ) in output
    assert "Codex CLI가 설치되어 있지 않습니다." in output


def test_auto_detect_first_run_preselects_detected(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from birkin import onboarding, provider_onboarding

    codex = provider_onboarding.CodexProviderStatus(True, "/tools/codex", None)
    missing = provider_onboarding.CodexProviderStatus(
        False,
        None,
        provider_onboarding.CodexProbeIssue.NOT_FOUND,
    )
    defaults: list[int] = []

    monkeypatch.setattr(
        provider_onboarding,
        "detect_engines",
        lambda: provider_onboarding.DetectedEngines(
            codex,
            missing,
            "codex-cli",
        ),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    monkeypatch.setattr(
        provider_onboarding,
        "probe_codex",
        lambda: (_ for _ in ()).throw(AssertionError("must not re-probe")),
    )

    def select(_prompt: str, _options: list[str], default: int = 0) -> int:
        defaults.append(default)
        return default

    monkeypatch.setattr(onboarding.menu, "select", select)

    assert onboarding._choose_provider("anthropic", first_run=True) == "codex-cli"
    assert defaults == [0]
    output = capsys.readouterr().out
    assert "  ✓ 자동 감지: Codex CLI (/tools/codex)" in output
    assert "  → 기본 엔진으로 codex-cli을(를) 선택했습니다." in output


def test_auto_detect_rerun_keeps_saved_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from birkin import onboarding, provider_onboarding

    providers = ["codex-cli", "claude-cli", "anthropic", "openai"]
    codex = provider_onboarding.CodexProviderStatus(True, "/tools/codex", None)
    missing = provider_onboarding.CodexProviderStatus(
        False,
        None,
        provider_onboarding.CodexProbeIssue.NOT_FOUND,
    )
    defaults: list[int] = []

    monkeypatch.setattr(
        provider_onboarding,
        "detect_engines",
        lambda: provider_onboarding.DetectedEngines(
            codex,
            missing,
            "codex-cli",
        ),
    )

    def select(_prompt: str, _options: list[str], default: int = 0) -> int:
        defaults.append(default)
        return default

    monkeypatch.setattr(onboarding.menu, "select", select)

    assert onboarding._choose_provider("anthropic", first_run=False) == "anthropic"
    assert defaults == [providers.index("anthropic")]
    output = capsys.readouterr().out
    assert "  ✓ 자동 감지: Codex CLI (/tools/codex)" in output
    assert "  → 기본 엔진으로" not in output


def test_auto_detect_claude_missing_prints_install_hint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from birkin import onboarding, provider_onboarding

    missing = provider_onboarding.CodexProviderStatus(
        False,
        None,
        provider_onboarding.CodexProbeIssue.NOT_FOUND,
    )
    monkeypatch.setattr(
        provider_onboarding,
        "detect_engines",
        lambda: provider_onboarding.DetectedEngines(missing, missing, None),
    )
    def select(_prompt: str, _options: list[str], default: int = 0) -> int:
        return 1

    monkeypatch.setattr(onboarding.menu, "select", select)

    assert onboarding._choose_provider("codex-cli", first_run=True) == "claude-cli"
    output = capsys.readouterr().out
    assert (
        "  ! Claude CLI를 찾지 못했습니다. 설치: "
        "npm install -g @anthropic-ai/claude-code"
    ) in output
    assert (
        "    설치 후 `birkin setup`을 다시 실행하거나, 지금 그대로 저장하고 "
        "나중에 PATH를 확인할 수 있습니다."
    ) in output


def test_auto_detect_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin import onboarding, provider_onboarding

    codex = provider_onboarding.CodexProviderStatus(True, "/tools/codex", None)
    claude = provider_onboarding.CodexProviderStatus(True, "/tools/claude", None)

    monkeypatch.setattr(
        provider_onboarding,
        "detect_engines",
        lambda: provider_onboarding.DetectedEngines(
            codex,
            claude,
            "codex-cli",
        ),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    def select(_prompt: str, _options: list[str], default: int = 0) -> int:
        assert default == 0
        return 1

    monkeypatch.setattr(onboarding.menu, "select", select)
    monkeypatch.setattr(
        provider_onboarding,
        "probe_codex",
        lambda: (_ for _ in ()).throw(AssertionError("must not re-probe")),
    )

    assert (
        onboarding._choose_provider("anthropic", first_run=True) == "claude-cli"
    )
