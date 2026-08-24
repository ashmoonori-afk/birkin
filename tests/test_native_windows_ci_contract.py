"""Machine-consumed contract for the dedicated native Windows workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypeAlias, cast

import yaml

WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "native-windows.yml"
EXPECTED_JOBS = {
    "python-windows",
    "dotnet-portable",
    "wpf-windows",
    "live-bridge-window",
    "protocol-fixture-freshness",
    "swift-conformance",
}
ACTION_PIN = re.compile(r"^[^@]+@[0-9a-f]{40}$")
GOLDEN_ROOT = "macos/BirkinNativeApp/Tests/BirkinNativeProtocolTests/GoldenVectors"
SOLUTION = "windows/BirkinNativeApp/BirkinNativeApp.sln"
YamlScalar: TypeAlias = str | int | float | bool | None
YamlValue: TypeAlias = YamlScalar | list["YamlValue"] | dict[str, "YamlValue"]
YamlMapping: TypeAlias = dict[str, YamlValue]

# PyYAML exposes an untyped boundary; casts stay here while assertions pin every
# consumed workflow node to its machine-readable contract.
def _mapping(value: YamlValue) -> YamlMapping:
    return cast(YamlMapping, value)


def _workflow() -> YamlMapping:
    return cast(
        YamlMapping,
        yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")),
    )


def _job(workflow: YamlMapping, name: str) -> YamlMapping:
    return _mapping(_mapping(workflow["jobs"])[name])


def _steps(job: YamlMapping) -> list[YamlMapping]:
    return cast(list[YamlMapping], job["steps"])


def _commands(job: YamlMapping) -> list[str]:
    return [cast(str, step["run"]) for step in _steps(job) if "run" in step]


def _joined_commands(job: YamlMapping) -> str:
    return "\n".join(_commands(job)).replace("\\", "/")


def test_dedicated_native_windows_workflow_exists() -> None:
    assert WORKFLOW.is_file(), f"missing dedicated workflow: {WORKFLOW}"


def test_triggers_cover_every_client_breaking_path() -> None:
    workflow = _workflow()
    raw_triggers = workflow.get("on")
    if raw_triggers is None:
        raw_triggers = cast(dict[str | bool, YamlValue], workflow)[True]
    triggers = _mapping(raw_triggers)
    assert {"push", "pull_request", "schedule", "workflow_dispatch"} <= set(triggers)

    required_paths = {
        "windows/**",
        "birkin/native/**",
        "birkin/workspace/**",
        "scripts/native/**",
        f"{GOLDEN_ROOT}/**",
        "docs/native-app/**",
        "pyproject.toml",
        "uv.lock",
        ".github/workflows/native-windows.yml",
        "tests/test_native_windows_import.py",
        "tests/test_native_windows_ci_contract.py",
    }
    for event in ("push", "pull_request"):
        config = _mapping(triggers[event])
        assert set(cast(list[str], config["paths"])) == required_paths


def test_workflow_uses_least_privilege_concurrency_and_pinned_actions() -> None:
    workflow = _workflow()
    assert set(_mapping(workflow["jobs"])) == EXPECTED_JOBS
    assert workflow["permissions"] == {"contents": "read"}
    assert _mapping(workflow["concurrency"]) == {
        "group": "native-windows-${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": True,
    }

    action_uses = [
        cast(str, step["uses"])
        for raw_job in _mapping(workflow["jobs"]).values()
        for step in _steps(_mapping(raw_job))
        if "uses" in step
    ]
    assert action_uses
    assert all(ACTION_PIN.fullmatch(action) for action in action_uses)


def test_python_windows_gate_uses_locked_python_313_and_import_contract() -> None:
    job = _job(_workflow(), "python-windows")
    assert job["runs-on"] == "windows-latest"
    steps = _steps(job)
    python = next(step for step in steps if str(step.get("uses", "")).startswith("actions/setup-python@"))
    assert _mapping(python["with"])["python-version"] == "3.13"
    assert any(str(step.get("uses", "")).startswith("astral-sh/setup-uv@") for step in steps)

    commands = _joined_commands(job)
    assert "uv sync --frozen" in commands
    assert "uv run --frozen pytest -q tests/test_native_windows_import.py" in commands


def test_portable_and_wpf_jobs_test_release_solution_with_dotnet_8() -> None:
    workflow = _workflow()
    portable = _job(workflow, "dotnet-portable")
    matrix = _mapping(_mapping(portable["strategy"])["matrix"])
    assert set(cast(list[str], matrix["os"])) == {
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
    }
    assert portable["runs-on"] == "${{ matrix.os }}"

    for name in ("dotnet-portable", "wpf-windows", "live-bridge-window"):
        job = _job(workflow, name)
        setup = next(
            step
            for step in _steps(job)
            if str(step.get("uses", "")).startswith("actions/setup-dotnet@")
        )
        assert _mapping(setup["with"])["dotnet-version"] == "8.x"

    wpf = _job(workflow, "wpf-windows")
    assert wpf["runs-on"] == "windows-latest"
    commands = _joined_commands(wpf)
    assert f"dotnet restore ./{SOLUTION}" in commands
    assert f"dotnet build ./{SOLUTION} -c Release --no-restore" in commands
    assert f"dotnet test ./{SOLUTION} -c Release --no-build" in commands


def test_fixture_freshness_regenerates_every_normative_vector() -> None:
    job = _job(_workflow(), "protocol-fixture-freshness")
    assert job["runs-on"] == "ubuntu-latest"
    commands = _joined_commands(job)
    assert "uv sync --frozen" in commands
    assert "uv run --frozen python scripts/native/generate_golden_vectors.py" in commands
    assert "uv run --frozen python scripts/native/generate_projection_vectors.py" in commands
    for fixture in (
        "native-protocol-vectors.json",
        "native-projection-vectors.json",
        "native-protocol-invalid-vectors.json",
    ):
        assert f"{GOLDEN_ROOT}/{fixture}" in commands
    assert "git diff --exit-code" in commands
    assert '"status", "--porcelain", "--untracked-files=all"' in commands
    assert "if status.stdout:" in commands
    assert "raise SystemExit(1)" in commands


def test_live_job_runs_real_authenticated_loopback_journey_and_only_uploads_trx() -> None:
    job = _job(_workflow(), "live-bridge-window")
    assert job["runs-on"] == "windows-latest"
    commands = _joined_commands(job)
    assert "uv sync --frozen" in commands
    assert "TestCategory=LiveBridge" in commands
    assert "--logger \"trx;LogFilePrefix=native-windows-live\"" in commands

    uploads = [
        step
        for step in _steps(job)
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 1
    upload = uploads[0]
    assert upload["if"] == "failure()"
    upload_config = _mapping(upload["with"])
    assert upload_config["path"] == "windows/BirkinNativeApp/**/TestResults/*.trx"
    assert upload_config["if-no-files-found"] == "error"


def test_swift_job_consumes_shared_vectors() -> None:
    job = _job(_workflow(), "swift-conformance")
    assert job["runs-on"] == "macos-latest"
    assert "swift test --package-path macos/BirkinNativeApp" in _joined_commands(job)


def test_jobs_use_platform_appropriate_shell_commands() -> None:
    workflow = _workflow()
    for name in ("python-windows", "wpf-windows", "live-bridge-window"):
        for step in _steps(_job(workflow, name)):
            command = step.get("run")
            if not isinstance(command, str):
                continue
            assert step.get("shell", "pwsh") == "pwsh"
            assert not any(token in command for token in ("set -o pipefail", "mkdir -p", "tee "))
