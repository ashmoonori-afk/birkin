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
    assert "tests/test_native_bridge_errors.py" in workflow
    assert "tests/test_native_bridge_capabilities.py" in workflow
    assert "tests/test_native_bridge_streaming.py" in workflow
    assert "tests/test_native_endpoint.py" in workflow
    assert "tests/test_native_import_direction.py" in workflow
    assert "Native protocol evidence" in workflow
    assert ".omo/evidence/native-protocol" in workflow
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


def test_tests_workflow_has_bounded_native_swift_job() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    native_job = workflow.split("  native-macos-swift:", 1)[1].split(
        "\n  windows-computer-use-native:", 1
    )[0]

    assert "native-macos-swift:" in workflow
    assert "name: Native macOS Swift build and test" in workflow
    assert "runs-on: macos-latest" in workflow
    assert "timeout-minutes: 20" in workflow
    assert "Verify Swift 6 toolchain" in workflow
    assert "swift --version | grep -E 'Swift version 6\\.'" in workflow
    assert "swift test --package-path macos/BirkinNativeApp" in workflow
    assert "actions/setup-python@" in native_job
    assert 'python-version: "3.13"' in native_job
    assert 'python -m pip install -e ".[browser]"' in native_job
    assert "python -m playwright install chromium" in native_job


def test_native_swift_job_uploads_test_evidence() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Native Swift test evidence" in workflow
    assert "if: always()" in workflow
    upload_action = (
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4"
    )
    assert upload_action in workflow
    assert "name: native-swift-test-evidence" in workflow
    assert "path: .omo/evidence/native-swift" in workflow
    assert "if-no-files-found: error" in workflow


def test_optional_workflow_is_separate_and_utf8() -> None:
    workflow = (WORKFLOW.parent / "optional-tests.yml").read_text(encoding="utf-8")
    assert "PYTHONUTF8" in workflow
    assert "office-advanced" in workflow
    assert "office-docling" not in workflow
