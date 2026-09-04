from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github/workflows/tests.yml"
JOB = "macos-computer-use-native"


def job_block(name: str) -> str:
    """Return one job's lines without importing a YAML parser.

    The workflow contract tests run on hosted runners that install only the
    project's declared extras, so this module stays on the standard library
    like the sibling workflow tests.
    """
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"  {name}:")
    end = start + 1
    while end < len(lines) and not (
        lines[end].startswith("  ")
        and not lines[end].startswith("   ")
        and lines[end].strip()
    ):
        end += 1
    return "\n".join(lines[start:end])


def test_hosted_macos_computer_use_job_is_explicit_and_retains_evidence() -> None:
    block = job_block(JOB)

    assert "runs-on: macos-latest" in block
    assert "--mode hosted" in block
    assert "test_computer_use_macos_dogfood.py" in block
    assert "test_macos_computer_use_ci_contract.py" in block
    assert 'rm -f "$RUNNER_TEMP/birkin-computer-use-fixture"' in block

    upload = block[block.index("actions/upload-artifact@") :]
    assert "if-no-files-found: warn" in upload
    assert "if: always()" in block[: block.index("actions/upload-artifact@")]


def test_permissioned_required_mode_is_never_run_on_a_hosted_runner() -> None:
    block = job_block(JOB)

    assert "permissioned-required" not in block
