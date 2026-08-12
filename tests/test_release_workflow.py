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
