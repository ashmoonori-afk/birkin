"""Tagged releases ship installable artifacts and integrity metadata."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_tag_release_workflow_builds_and_publishes_artifacts() -> None:
    workflow = (_ROOT / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )
    required = (
        "tags:",
        "- \"v*\"",
        "contents: write",
        "python -m build",
        "SHA256SUMS",
        "gh release create",
        "--generate-notes",
        "dist/*.whl",
        "dist/*.tar.gz",
    )
    for fragment in required:
        assert fragment in workflow


def test_native_macos_release_is_conditional_and_keeps_symbols_separate() -> None:
    workflow = (_ROOT / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )

    assert "native-macos-release:" in workflow
    assert "vars.BIRKIN_PUBLISH_MACOS == '1'" in workflow
    assert "scripts/native/package_macos_app.sh dist/native-macos" in workflow
    assert "scripts/native/create_macos_dmg.sh dist/native-macos" in workflow
    assert "Verify native artifact and symbol UUID identity" in workflow
    assert "private-native-symbols-" in workflow
    assert "retention-days: 14" in workflow

    release_upload = workflow.split(
        "- name: Publish native customer artifacts", 1
    )[1].split("- name: Upload matching private native symbols", 1)[0]
    assert "*.dmg" in release_upload
    assert "artifact-manifest.sha256" in release_upload
    assert "build-manifest.txt" in release_upload
    assert "symbols.zip" not in release_upload

    symbol_upload = workflow.split(
        "- name: Upload matching private native symbols", 1
    )[1]
    assert "*-symbols.zip" in symbol_upload
    assert "*-symbols.zip.sha256" in symbol_upload
    assert "*-symbols-manifest.txt" in symbol_upload
