"""P1-7 publication contracts for Windows and first-report onboarding."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_powershell_installer_promotes_setup_before_chat() -> None:
    script = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert "birkin setup" in script
    assert "birkin chat" in script
    assert "birkin --version" in script
    assert "python -m birkin --version" in script
    assert '[Environment]::SetEnvironmentVariable("Path"' in script
    assert "[IO.Path]::GetPathRoot" in script
    assert "[StringComparer]::OrdinalIgnoreCase" in script
    assert '.TrimEnd("\\")' not in script
    assert "setx PATH" not in script
    assert "ANTHROPIC_API_KEY" not in script
    assert "04:00" not in script
    assert "07:00" in script
    assert "@(& $name" in script
    assert ".Count -eq 1" in script
    assert "git+" not in script
    assert "/archive/$Ref.zip" in script


def test_readmes_publish_windows_install_and_safe_persistence() -> None:
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    korean = (ROOT / "README.ko.md").read_text(encoding="utf-8")

    for text in (english, korean):
        quick_start = (
            text.index("## Quick Start")
            if "## Quick Start" in text
            else text.index("## 빠른 시작")
        )
        powershell = text.index("scripts/install.ps1", quick_start)
        source_install = text.index("python -m pip install .", quick_start)
        assert powershell < source_install
        assert "scripts/install.ps1" in text
        assert 'setx BIRKIN_HOME "$env:USERPROFILE\\.birkin"' in text
        assert "setx PATH" in text
        assert "reg delete HKCU\\Environment /v BIRKIN_HOME /f" in text
        assert "setx ANTHROPIC_API_KEY" not in text
        assert "04:00" not in text
        assert "07:00" in text

        first_steps = text[quick_start:source_install]
        assert "ANTHROPIC_API_KEY" not in first_steps


def test_korean_readme_has_ten_minute_office_report_track() -> None:
    korean = (ROOT / "README.ko.md").read_text(encoding="utf-8")

    first_report_path = korean.index(
        'Join-Path $env:USERPROFILE "Documents\\매출.xlsx"',
    )
    detailed_reference = korean.index("office_rollback_request")
    assert first_report_path < korean.index("## 왜 birkin인가")
    assert first_report_path < detailed_reference
    assert 'python -m pip install ".[office]"' in korean
    assert "birkin setup" in korean
    assert 'Join-Path $env:USERPROFILE ".birkin\\office\\artifacts\\incoming"' in korean
    assert "birkin review" in korean
    assert "office_rollback_request" in korean


def test_fresh_windows_journey_runs_installer_and_local_chat() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "fresh-windows-journey.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "runs-on: windows-latest" in workflow
    assert 'BIRKIN_REF: "${{ github.sha }}"' in workflow
    assert ".\\scripts\\install.ps1" in workflow
    assert "birkin --help" in workflow
    assert "birkin definitely-not-a-command" in workflow
    assert "birkin setup" in workflow
    assert "Codex CLI가 설치되어 있지 않습니다." in workflow
    assert "qwen2.5:0.5b" in workflow
    assert "birkin chat" in workflow
    assert "fresh-windows-first-chat" in workflow
    assert 'base_url = "http://127.0.0.1:11434"' in workflow
    assert 'base_url = "http://127.0.0.1:11434/v1"' not in workflow
    assert "ErrorDataReceived" in workflow
    assert "BeginErrorReadLine" in workflow
    assert "$server.Kill($true)" in workflow
    assert "catch [InvalidOperationException]" in workflow
    assert "$server.WaitForExit(10000)" in workflow
    assert "FileSystemWatcher" not in workflow
