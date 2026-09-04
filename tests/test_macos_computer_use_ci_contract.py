from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml

WORKFLOW = Path(__file__).parents[1] / ".github/workflows/tests.yml"


def mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def mappings(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    items = cast(list[object], value)
    return [mapping(item) for item in items]


def test_hosted_macos_computer_use_job_is_explicit_and_retains_evidence() -> None:
    workflow = mapping(cast(object, yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))))
    jobs = mapping(workflow["jobs"])
    job = mapping(jobs["macos-computer-use-native"])
    steps = mappings(job["steps"])
    commands = "\n".join(
        run for step in steps if isinstance((run := step.get("run")), str)
    )

    assert "--mode hosted" in commands
    assert "test_computer_use_macos_dogfood.py" in commands
    assert "test_macos_computer_use_ci_contract.py" in commands
    assert 'rm -f "$RUNNER_TEMP/birkin-computer-use-fixture"' in commands
    upload = next(
        step
        for step in steps
        if isinstance((uses := step.get("uses")), str)
        and uses.startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "always()"
    assert mapping(upload["with"])["if-no-files-found"] == "error"
