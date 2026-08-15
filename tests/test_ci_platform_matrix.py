from __future__ import annotations

from pathlib import Path

WORKFLOW = (
    Path(__file__).parents[1] / ".github" / "workflows" / "tests.yml"
)


def test_tests_workflow_runs_for_feature_branch_pushes() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "branches: [main]" not in workflow
    assert "\n  push:\n" in workflow


def test_tests_workflow_covers_supported_operating_systems() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ubuntu-latest" in workflow
    assert "macos-latest" in workflow
    assert "windows-latest" in workflow
    assert workflow.count("python -m pytest") == 3
    assert "Native Windows shell acceptance" in workflow
    assert "Native macOS shell acceptance" in workflow
    assert "tests/test_generic_shell_paths.py" in workflow
    assert "tests/test_macos_shell_acceptance.py" in workflow
    assert "tests/test_windows_job_object.py" in workflow
    assert "tests/test_windows_shell_matrix.py" in workflow
    assert "scripts/qa/macos_shell_smoke.py" in workflow
    assert "scripts/qa/windows_shell_smoke.py" in workflow
    assert "runner.os != 'Linux'" in workflow
    assert "Windows CLI invalid input" in workflow
    assert "Windows security scan" in workflow
    assert 'python: "3.10"' in workflow
