from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import yaml

WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "office-tests.yml"
PLATFORM_WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "tests.yml"
REQUIRED_OSES = {"ubuntu-latest", "macos-latest", "windows-latest"}


def _mapping(value: object) -> dict[str, object]:
    return cast(dict[str, object], value)


def _load_workflow(path: Path = WORKFLOW) -> dict[str, object]:
    return cast(dict[str, object], yaml.safe_load(path.read_text(encoding="utf-8")))


def _workflow() -> dict[str, object]:
    return _load_workflow()


def _steps(job: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], job["steps"])


def _runs(job: dict[str, object]) -> list[str]:
    return [cast(str, step["run"]) for step in _steps(job) if "run" in step]


def _job(workflow: dict[str, object], name: str) -> dict[str, object]:
    return _mapping(_mapping(workflow["jobs"])[name])


def test_general_platform_suite_installs_office_dependencies() -> None:
    job = _job(_load_workflow(PLATFORM_WORKFLOW), "platform-suite")
    matrix = _mapping(_mapping(job["strategy"])["matrix"])
    entries = cast(list[dict[str, str]], matrix["include"])
    assert {entry["os"] for entry in entries} == REQUIRED_OSES

    runs = _runs(job)
    assert any("python -m pytest" in command for command in runs)
    install = next(command for command in runs if "pip install -e" in command)
    assert '".[dev,office,office-advanced,browser]"' in install
    assert any("playwright install" in command for command in runs)
    assert _mapping(job["env"])["BIRKIN_BROWSER_INTEGRATION"] == "1"


def test_required_office_job_has_three_os_matrix_and_bounded_environment() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}

    job = _job(workflow, "office-core")
    strategy = _mapping(job["strategy"])
    matrix = _mapping(strategy["matrix"])
    assert set(cast(list[str], matrix["os"])) == REQUIRED_OSES
    assert job["runs-on"] == "${{ matrix.os }}"
    assert strategy["fail-fast"] is False

    uses = [cast(str, step["uses"]) for step in _steps(job) if "uses" in step]
    assert any(value.startswith("astral-sh/setup-uv@") for value in uses)
    runs = _runs(job)
    sync = next(command for command in runs if command.startswith("uv sync "))
    assert "--locked" in sync
    assert "--extra office" in sync
    assert "--extra office-advanced" in sync


def test_required_office_job_runs_objective_checks_and_install_smoke() -> None:
    runs = _runs(_job(_workflow(), "office-core"))

    required_fragments = {
        "python -m compileall -q birkin",
        "tests/office",
        "tests/test_document_tools.py",
        "test_package_boundaries.py",
        "test_package_resource_boundaries.py",
        "tests/test_office_skill.py",
        "python -m birkin skills validate",
        "office_work_os_dogfood.py",
        "uv build --wheel",
        "uv pip install",
    }
    for fragment in required_fragments:
        assert any(fragment in command for command in runs), fragment

    serialized = yaml.safe_dump(_workflow())
    assert "continue-on-error" not in serialized
    assert "dummy" not in serialized.lower()
    assert "mocked renderer" not in serialized.lower()


def test_clean_wheel_smoke_runs_outside_checkout_and_probes_office_resources() -> None:
    job = _job(_workflow(), "office-core")
    smoke = next(command for command in _runs(job) if "office-wheel-smoke" in command)
    step = next(step for step in _steps(job) if step.get("run") == smoke)

    assert step["shell"] == "python"
    assert ".resolve()" in smoke
    assert "cwd=outside" in smoke
    assert 'wheel_requirement = f"birkin @ {wheel.as_uri()}"' in smoke
    assert "wheel.as_uri()" in smoke
    assert 'environment.pop("PYTHONPATH"' in smoke
    assert "GITHUB_WORKSPACE" in smoke
    assert "import birkin.office" in smoke
    assert "from birkin.office.service_workspace import DocumentWorkspace" in smoke
    assert "workspace.atomic_publish" in smoke
    assert "workspace.resolve_artifact" in smoke
    assert "_bundled_skills" in smoke
    assert "office-work-os" in smoke
    assert "office-documents" in smoke
    assert "provenance_manifest.json" in smoke
    assert "office_base_wheel_smoke.py" in smoke
    assert '"-I"' in smoke


def test_cross_platform_steps_use_runner_native_or_python_shells() -> None:
    workflow = _workflow()
    for job_name in ("office-core",):
        for step in _steps(_job(workflow, job_name)):
            command = step.get("run")
            if not isinstance(command, str):
                continue
            shell = step.get("shell")
            assert shell in {None, "python", "uv run --no-sync python {0}"}
            if "import pathlib" in command:
                assert shell in {"python", "uv run --no-sync python {0}"}


def test_workflow_has_no_external_application_engine_job() -> None:
    workflow = _workflow()
    assert set(_mapping(workflow["jobs"])) == {"office-core"}
    serialized = json.dumps(workflow).casefold()
    for forbidden in (
        "libreoffice",
        "soffice",
        "pandoc",
        "unoconv",
        "office_real_engine",
    ):
        assert forbidden not in serialized
