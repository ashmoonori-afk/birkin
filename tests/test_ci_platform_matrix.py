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
    assert workflow.count("python -m pytest") == 1
    assert 'python: "3.10"' in workflow


def test_optional_workflow_is_separate_and_utf8() -> None:
    workflow = (WORKFLOW.parent / "optional-tests.yml").read_text(encoding="utf-8")
    assert "PYTHONUTF8" in workflow
    assert "office-advanced" in workflow
    assert "office-docling" not in workflow
