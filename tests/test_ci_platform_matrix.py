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
    assert workflow.count("python -m pytest") == 4
    assert "Native local protocol foundation" in workflow
    assert "tests/test_native_bridge_server.py" in workflow
    assert "tests/test_native_import_direction.py" in workflow
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


def test_primary_ci_excludes_exact_lock_only_tests() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '-m "not live and not locked_env"' in workflow


def test_optional_workflow_is_separate_and_utf8() -> None:
    workflow = (WORKFLOW.parent / "optional-tests.yml").read_text(encoding="utf-8")
    assert "PYTHONUTF8" in workflow
    assert "office-advanced" in workflow
    assert "office-docling" not in workflow
