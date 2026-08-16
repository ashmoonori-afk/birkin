from __future__ import annotations

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
    assert '".[dev,office,office-advanced]"' in install


def test_required_office_job_has_three_os_matrix_and_locked_environment() -> None:
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
    assert any(
        "uv sync --locked" in command
        and "--extra office" in command
        and "--extra office-advanced" in command
        for command in runs
    )


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
    assert "birkin[office,office-advanced]" in smoke
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


def test_cross_platform_steps_use_runner_native_or_python_shells() -> None:
    workflow = _workflow()
    for job_name in ("office-core", "office-real"):
        for step in _steps(_job(workflow, job_name)):
            command = step.get("run")
            if not isinstance(command, str):
                continue
            shell = step.get("shell")
            assert shell in {None, "python", "uv run --no-sync python {0}"}
            if "import pathlib" in command:
                assert shell in {"python", "uv run --no-sync python {0}"}


def test_optional_external_engine_job_is_explicitly_capability_gated() -> None:
    workflow = _workflow()
    job = _job(workflow, "office-real")
    condition = cast(str, job["if"])

    assert "vars.OFFICE_REAL_RUNNER" in condition
    assert "vars.OFFICE_REAL_ENGINE == 'libreoffice'" in condition
    assert "office-core" not in cast(list[str], job.get("needs", []))
    assert job["runs-on"] == ["self-hosted", "${{ vars.OFFICE_REAL_RUNNER }}"]

    environment = _mapping(job["env"])
    assert environment["OFFICE_LIBREOFFICE_VERSION"] == "${{ vars.OFFICE_LIBREOFFICE_VERSION }}"
    exercise = next(command for command in _runs(job) if "status.json" in command)
    assert "approved_executable_not_present" in exercise
    assert "--version" in exercise
    assert "OFFICE_LIBREOFFICE_VERSION" in exercise
    assert "actual_version != expected_version" in exercise
    assert "SystemExit(0)" not in exercise

    upload = next(
        step
        for step in _steps(job)
        if cast(str, step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    settings = _mapping(upload["with"])
    assert settings["path"] == "office-real-evidence/status.json"
    assert cast(int, settings["retention-days"]) <= 7


def test_real_engine_script_uses_uv_managed_project_interpreter() -> None:
    job = _job(_workflow(), "office-real")
    exercise_step = next(
        step for step in _steps(job) if "status.json" in str(step.get("run", ""))
    )
    exercise = cast(str, exercise_step["run"])

    assert exercise_step["shell"] == "uv run --no-sync python {0}"
    assert "sys.executable" in exercise
    assert '"script/qa/office_work_os_dogfood.py"' in exercise


def test_real_engine_uses_edited_receipts_and_exact_output_mapping() -> None:
    exercise = next(
        command
        for command in _runs(_job(_workflow(), "office-real"))
        if "status.json" in command
    )

    assert "next(work.rglob" not in exercise
    assert 'report["formats"]' in exercise
    assert '["artifacts"]' in exercise
    assert '["modify"]' in exercise
    assert "modified-{format_name}.{format_name}" in exercise
    assert 'format_receipt["operations"]["modify"]["artifact"]' in exercise
    assert 'format_receipt["primary_artifact"]' in exercise
    assert 'receipt["sha256"]' in exercise
    assert "hashlib.sha256" in exercise
    assert '"selected_receipts"' in exercise
    assert '"output_mapping"' in exercise
    assert "outputs == sorted(expected_output_mapping.values())" in exercise
